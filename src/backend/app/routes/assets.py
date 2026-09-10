"""Module assets: upload, list, delete, and authorized delivery.

Two routers, because these are two different audiences on two different paths:

* `router` (`/api/content/...`) is authoring — Content Managers and
  Administrators adding and removing material.
* `delivery_router` (`/api/modules/{id}/assets/{asset_id}`) is *reading* one
  asset. Every audience eventually arrives here: an author previewing, and (as
  of ticket 5) a learner reading the published module. It is the path the
  checked-in ProseMirror schema pins an `image` node's `src` to, so it is a
  stable URL rather than an implementation detail.

Nothing is ever served from the bucket directly. A read goes through the API,
which authorizes the caller against the *module* and only then mints a
presigned URL with a five-minute TTL. The redirect is the whole point: the
bytes leave from an origin that is not the application's, so even a hypothetical
content-type escape has no same-origin document to attack.
"""

import uuid
from typing import Annotated, cast

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.content.uploads import UploadRejected, sniff_upload
from app.core.config import get_settings
from app.db import get_db
from app.dependencies import (
    get_asset_signing_client,
    get_module_or_404,
    get_s3_client,
    require_active_user,
    require_content_manager,
)
from app.models import Module, ModuleAsset, User
from app.schemas.modules import AssetKind, AssetResponse, AssetsResponse, ModuleActor
from app.security.audit import record_audit_log
from app.storage import S3Client, delete_asset, object_key, presigned_asset_url, put_asset

router = APIRouter(prefix="/api/content", tags=["content"])
delivery_router = APIRouter(prefix="/api/modules", tags=["assets"])

_ASSET_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found.")

# Read the body in pieces so the per-file cap can refuse an oversized upload
# part-way through rather than after materialising all of it.
_CHUNK_BYTES = 64 * 1024


def asset_url(module_id: uuid.UUID, asset_id: uuid.UUID) -> str:
    """The stable, authorizing URL for an asset.

    Must keep matching `imageSrcPattern` in the checked-in ProseMirror schema —
    an `image` node whose `src` is anything else is a rejected document.
    """
    return f"/api/modules/{module_id}/assets/{asset_id}"


async def _reference_counts(
    db: AsyncSession, module_id: uuid.UUID
) -> dict[uuid.UUID, tuple[int, int]]:
    """Who still points at each of this module's assets: draft pages, and
    published versions.

    Two counts rather than one, because they are two different warnings. A
    draft page losing an image is something the author can see and fix in the
    editor. A *published* version losing one cannot be fixed at all — a version
    snapshot is immutable, so the image is simply gone from material learners
    are reading right now, with no edit available that would put it back.

    Matched against the stored document trees with a jsonpath rather than a
    substring search over the serialized JSON — a `src` is a `src`, not a
    coincidence in some other string — and across both the attributes a body
    can reference an asset with, since a linked PDF breaks exactly as an
    embedded image does.
    """
    rows = await db.execute(
        text(
            """
            WITH referenced AS (
                SELECT
                    a.id AS asset_id,
                    :prefix || a.id::text AS url
                FROM module_assets a
                WHERE a.module_id = :module_id
            )
            SELECT
                r.asset_id,
                (
                    SELECT count(*)
                    FROM module_pages p
                    WHERE p.module_id = :module_id
                      AND (
                        jsonb_path_exists(
                            p.body, '$.**.src ? (@ == $url)',
                            jsonb_build_object('url', r.url)
                        )
                        OR jsonb_path_exists(
                            p.body, '$.**.href ? (@ == $url)',
                            jsonb_build_object('url', r.url)
                        )
                      )
                ) AS pages,
                (
                    SELECT count(*)
                    FROM module_versions v
                    WHERE v.module_id = :module_id
                      AND (
                        jsonb_path_exists(
                            v.snapshot, '$.**.src ? (@ == $url)',
                            jsonb_build_object('url', r.url)
                        )
                        OR jsonb_path_exists(
                            v.snapshot, '$.**.href ? (@ == $url)',
                            jsonb_build_object('url', r.url)
                        )
                      )
                ) AS versions
            FROM referenced r
            """
        ),
        {"module_id": module_id, "prefix": f"/api/modules/{module_id}/assets/"},
    )
    return {row.asset_id: (row.pages, row.versions) for row in rows}


async def _assets_response(db: AsyncSession, module: Module) -> AssetsResponse:
    settings = get_settings()
    assets = list(
        (
            await db.execute(
                select(ModuleAsset)
                .where(ModuleAsset.module_id == module.id)
                .order_by(ModuleAsset.created_at.desc())
            )
        ).scalars()
    )
    references = await _reference_counts(db, module.id)

    uploader_ids = {asset.uploaded_by for asset in assets}
    uploaders: dict[uuid.UUID, ModuleActor] = {}
    if uploader_ids:
        users = (await db.execute(select(User).where(User.id.in_(uploader_ids)))).scalars()
        uploaders = {user.id: ModuleActor.from_user(user) for user in users}

    return AssetsResponse(
        assets=[
            AssetResponse(
                id=asset.id,
                # The DB's `ck_module_assets_kind` constraint is what makes this
                # narrowing sound; nothing else can have been written.
                kind=cast(AssetKind, asset.kind),
                url=asset_url(module.id, asset.id),
                content_type=asset.content_type,
                size_bytes=asset.size_bytes,
                original_filename=asset.original_filename,
                uploaded_by=uploaders[asset.uploaded_by],
                created_at=asset.created_at,
                referenced_by_pages=references.get(asset.id, (0, 0))[0],
                referenced_by_versions=references.get(asset.id, (0, 0))[1],
            )
            for asset in assets
        ],
        total_bytes=sum(asset.size_bytes for asset in assets),
        max_module_bytes=settings.asset_max_module_bytes,
        max_image_bytes=settings.asset_max_image_bytes,
        max_attachment_bytes=settings.asset_max_attachment_bytes,
    )


@router.get("/modules/{module_id}/assets", response_model=AssetsResponse)
async def list_assets(
    module_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    author: User = Depends(require_content_manager),
) -> AssetsResponse:
    module = await get_module_or_404(db, module_id)
    return await _assets_response(db, module)


async def _read_within_cap(upload: UploadFile, limit: int) -> bytes:
    """Read the upload, refusing it the moment it exceeds its cap.

    What this does guarantee is that nothing is *persisted* before the size is
    known to be acceptable — neither a row nor an object.

    What it does not: Starlette parses the whole multipart body (spooling past
    1 MB to a temp file) before this handler is entered, so by the time the cap
    trips, the bytes have already been received. The guard that actually stops a
    hostile body reaching the application is `client_max_body_size` in nginx.
    """
    pieces: list[bytes] = []
    total = 0
    while chunk := await upload.read(_CHUNK_BYTES):
        total += len(chunk)
        if total > limit:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail={
                    "code": "file_too_large",
                    "message": f"This file is larger than the {limit // (1024 * 1024)} MB limit.",
                    "limit_bytes": limit,
                },
            )
        pieces.append(chunk)
    return b"".join(pieces)


@router.post(
    "/modules/{module_id}/assets",
    response_model=AssetsResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_asset(
    module_id: uuid.UUID,
    kind: Annotated[AssetKind, Form()],
    file: Annotated[UploadFile, File()],
    db: AsyncSession = Depends(get_db),
    author: User = Depends(require_content_manager),
    s3_client: S3Client = Depends(get_s3_client),
) -> AssetsResponse:
    """Add an image or a downloadable file to a module.

    Deliberately *not* a `draft_revision` mutation. Adding an asset is additive
    — it cannot overwrite a colleague's sentence — and bumping the token would
    invalidate the author's own next page save, so inserting an image would
    409 on the very save that references it.
    """
    settings = get_settings()
    module = await get_module_or_404(db, module_id)

    limit = (
        settings.asset_max_image_bytes
        if kind == "image"
        else settings.asset_max_attachment_bytes
    )
    data = await _read_within_cap(file, limit)

    # What the client *declared* the type to be is never consulted: this reads
    # the bytes, and requires the filename extension to agree with them.
    try:
        sniffed = sniff_upload(data, kind=kind, filename=file.filename or "")
    except UploadRejected as rejection:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail={"code": rejection.code, "message": rejection.message},
        ) from rejection

    stored_bytes = (
        await db.execute(
            select(func.coalesce(func.sum(ModuleAsset.size_bytes), 0)).where(
                ModuleAsset.module_id == module.id
            )
        )
    ).scalar_one()
    if stored_bytes + len(data) > settings.asset_max_module_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail={
                "code": "module_quota_exceeded",
                "message": (
                    "This module has reached its total storage limit of "
                    f"{settings.asset_max_module_bytes // (1024 * 1024)} MB. "
                    "Remove an asset before adding another."
                ),
                "limit_bytes": settings.asset_max_module_bytes,
            },
        )

    asset_id = uuid.uuid4()
    key = object_key(module.id, asset_id)
    db.add(
        ModuleAsset(
            id=asset_id,
            module_id=module.id,
            kind=kind,
            object_key=key,
            content_type=sniffed.content_type,
            size_bytes=len(data),
            original_filename=sniffed.filename,
            uploaded_by=author.id,
        )
    )
    # Flushed before the object is written, so a failed insert leaves nothing
    # in the bucket. The reverse order would strand an object with no row
    # pointing at it and no way to find it again.
    await db.flush()

    await put_asset(
        s3_client,
        key=key,
        data=data,
        content_type=sniffed.content_type,
        # Images render in place; everything else is a download, and says so on
        # the object rather than only in the URL that fetches it.
        download_filename=None if kind == "image" else sniffed.filename,
    )

    await record_audit_log(
        db,
        actor_user_id=author.id,
        action="module_asset_uploaded",
        detail={
            "module_id": str(module.id),
            "asset_id": str(asset_id),
            "kind": kind,
            "content_type": sniffed.content_type,
            "size_bytes": len(data),
            "original_filename": sniffed.filename,
        },
    )
    await db.commit()
    return await _assets_response(db, module)


@router.delete("/modules/{module_id}/assets/{asset_id}", response_model=AssetsResponse)
async def delete_module_asset(
    module_id: uuid.UUID,
    asset_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    author: User = Depends(require_content_manager),
    s3_client: S3Client = Depends(get_s3_client),
) -> AssetsResponse:
    """Remove an asset, and the stored object with it.

    An asset a page still embeds may be deleted: the author is told how many
    pages use it before they confirm, and refusing outright would leave no way
    to remove material that has to go. What is never allowed is the object
    outliving the row — an unreferenced object nobody can enumerate is exactly
    the thing a private bucket is supposed not to accumulate.
    """
    module = await get_module_or_404(db, module_id)
    # Scoped to the module in the URL, so an asset id from another module is a
    # 404 rather than a deletion applied to somebody else's material.
    asset = (
        await db.execute(
            select(ModuleAsset).where(
                ModuleAsset.id == asset_id, ModuleAsset.module_id == module.id
            )
        )
    ).scalar_one_or_none()
    if asset is None:
        raise _ASSET_NOT_FOUND

    key = asset.object_key
    detail = {
        "module_id": str(module.id),
        "asset_id": str(asset.id),
        "kind": asset.kind,
        "original_filename": asset.original_filename,
    }
    await db.delete(asset)
    await db.flush()

    # Before the commit: if the store refuses, the transaction rolls back and
    # the row survives alongside the object it describes.
    await delete_asset(s3_client, key=key)

    await record_audit_log(
        db, actor_user_id=author.id, action="module_asset_deleted", detail=detail
    )
    await db.commit()
    return await _assets_response(db, module)


# --- Delivery -------------------------------------------------------------


def authorize_asset_access(user: User, module: Module) -> None:
    """May this user read this module's assets?

    Implicit deny: an authenticated user gets nothing until a rule admits them.
    Today the only rule is authoring — Content Managers and Administrators may
    read any module's assets, which is the same access they already have to its
    pages.

    Ticket 5 adds the learner branches (the module is catalog-visible, or it is
    assigned to them) and this function is where they go, so there is exactly
    one place that decides — expect it to grow an `AsyncSession` parameter and
    become a coroutine then, since both of those branches need a lookup.
    Everyone else gets a 404 rather than a 403: whether a particular asset
    exists is not something to confirm to somebody who may not read it.
    """
    if not {"Content Manager", "Administrator"} & {role.name for role in user.roles}:
        raise _ASSET_NOT_FOUND


@delivery_router.get("/{module_id}/assets/{asset_id}")
async def get_asset(
    module_id: uuid.UUID,
    asset_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_active_user),
    signing_client: S3Client = Depends(get_asset_signing_client),
) -> Response:
    """Authorize, then redirect to a short-lived presigned URL.

    The signed URL is never put in a JSON body or logged — it is a bearer
    credential for one object, and it goes straight into a `Location` header
    the browser follows and then forgets.
    """
    module = (
        await db.execute(select(Module).where(Module.id == module_id))
    ).scalar_one_or_none()
    if module is None:
        raise _ASSET_NOT_FOUND
    authorize_asset_access(user, module)

    asset = (
        await db.execute(
            select(ModuleAsset).where(
                ModuleAsset.id == asset_id, ModuleAsset.module_id == module.id
            )
        )
    ).scalar_one_or_none()
    if asset is None:
        raise _ASSET_NOT_FOUND

    url = await presigned_asset_url(signing_client, key=asset.object_key)
    return Response(
        status_code=status.HTTP_307_TEMPORARY_REDIRECT,
        headers={
            "Location": url,
            # Short, and always shorter than the signature's own lifetime, so a
            # cached redirect can never point at an expired URL. `private`
            # because the decision behind it was made about one user.
            "Cache-Control": "private, max-age=60",
            "Referrer-Policy": "no-referrer",
        },
    )
