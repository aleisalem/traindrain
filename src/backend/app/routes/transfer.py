"""Native export and import: a module as a self-contained `.zip`.

An export is a snapshot of the *draft* — the same pages an author is working
on, not a published version snapshot — because the point of moving a module
between deployments is to keep editing it on the other side. An import always
lands as a fresh, unpublished draft (its own new translation group, its own
new asset objects, its own new page rows): nothing here writes to an existing
module, and nothing here publishes one. Every imported page tree goes through
`app.routes.content.validate_page_body` — the same server-side ProseMirror
validator authored content goes through — and every imported asset goes
through `app.content.uploads.sniff_upload` — the same byte-level sniffing a
fresh upload goes through. Neither gets a shortcut for having arrived inside
our own format.

The archive itself is hostile input: see `app.content.transfer` for the
zip-bomb and path-traversal defenses applied before any entry is trusted.
"""

import logging
import re
import uuid
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.content import (
    CONSTRAINTS,
    SCHEMA_VERSION,
    TEXT_SEARCH_CONFIGS,
    DocumentValidationError,
    extract_search_text,
    validate_document,
)
from app.content.transfer import ArchiveRejected, build_export_archive, parse_export_archive
from app.content.uploads import UploadRejected, sniff_upload
from app.core.config import get_settings
from app.db import get_db
from app.dependencies import get_module_or_404, get_s3_client, require_content_manager
from app.models import Module, ModuleAsset, ModulePage, ModuleTranslationGroup, User
from app.routes.assets import asset_url, read_upload_within_cap
from app.routes.content import module_response, validate_page_body
from app.schemas.modules import AssetKind, ModuleLanguage, ModuleResponse
from app.schemas.transfer import EXPORT_FORMAT, ExportedAsset, ExportedPage, ModuleExportDocument
from app.security.audit import record_audit_log
from app.storage import S3Client, delete_asset, get_asset_bytes, object_key, put_asset

router = APIRouter(prefix="/api/content", tags=["content"])

logger = logging.getLogger(__name__)

_MAX_PAGES: int = CONSTRAINTS["limits"]["maxPagesPerModule"]

# The attributes a page body can point at an asset with — mirrors
# `app.routes.content._ASSET_REFERENCE_ATTRIBUTES`; kept as its own copy
# rather than an import because it is a fact about the schema (which two
# attributes carry an asset reference), not state either module owns.
_ASSET_REFERENCE_ATTRIBUTES = frozenset({"src", "href"})

# An asset reference URL, captured for its trailing asset id only. An
# imported manifest carries no record of which module it used to belong to,
# so — unlike `app.routes.content._rewrite_asset_references`, which matches a
# duplicate's pages against one known source module — rewriting on import
# matches by asset id alone, which is the one part of the URL that survives
# the move.
_ASSET_URL_PATTERN = re.compile(
    r"^/api/modules/[0-9a-fA-F-]{36}/assets/(?P<asset_id>[0-9a-fA-F-]{36})$"
)

_UNSAFE_FILENAME_CHARS = re.compile(r"[^A-Za-z0-9._-]+")


def _export_filename(title: str) -> str:
    """A safe, ASCII-only `.zip` filename derived from a module's title.

    Built from a conservative allowlist rather than escaped, so there is no
    header-injection surface to reason about in the `Content-Disposition`
    this is placed into.
    """
    slug = _UNSAFE_FILENAME_CHARS.sub("-", title).strip("-.")
    return f"{slug or 'module'}.zip"


async def _module_pages_ordered(db: AsyncSession, module_id: uuid.UUID) -> list[ModulePage]:
    return list(
        (
            await db.execute(
                select(ModulePage)
                .where(ModulePage.module_id == module_id)
                .order_by(ModulePage.position)
            )
        ).scalars()
    )


async def _module_assets_ordered(db: AsyncSession, module_id: uuid.UUID) -> list[ModuleAsset]:
    return list(
        (
            await db.execute(
                select(ModuleAsset)
                .where(ModuleAsset.module_id == module_id)
                .order_by(ModuleAsset.created_at)
            )
        ).scalars()
    )


@router.get("/modules/{module_id}/export")
async def export_module(
    module_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    author: User = Depends(require_content_manager),
    s3_client: S3Client = Depends(get_s3_client),
) -> Response:
    """A module's draft, its pages, and its assets, as a self-contained `.zip`.

    Deliberately not gated on the module's status: a deleted module's
    tombstone is a legitimate thing to read (`GET .../versions` and the module
    itself already work this way) — it simply exports to an archive with no
    pages and no assets, since a delete purges both.
    """
    module = await get_module_or_404(db, module_id)
    pages = await _module_pages_ordered(db, module.id)
    assets = await _module_assets_ordered(db, module.id)

    asset_bytes: dict[uuid.UUID, bytes] = {}
    for asset in assets:
        asset_bytes[asset.id] = await get_asset_bytes(s3_client, key=asset.object_key)

    document = ModuleExportDocument(
        format=EXPORT_FORMAT,
        title=module.title,
        description=module.description,
        language=cast(ModuleLanguage, module.language),
        estimated_duration_minutes=module.estimated_duration_minutes,
        pages=[
            ExportedPage(title=page.title, schema_version=page.schema_version, body=page.body)
            for page in pages
        ],
        assets=[
            ExportedAsset(
                id=asset.id,
                kind=cast(AssetKind, asset.kind),
                content_type=asset.content_type,
                original_filename=asset.original_filename,
                size_bytes=asset.size_bytes,
            )
            for asset in assets
        ],
    )
    archive = build_export_archive(document, asset_bytes)

    await record_audit_log(
        db,
        actor_user_id=author.id,
        action="module_exported",
        detail={
            "module_id": str(module.id),
            "title": module.title,
            "page_count": len(pages),
            "asset_count": len(assets),
        },
    )
    await db.commit()

    return Response(
        content=archive,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{_export_filename(module.title)}"',
        },
    )


def _rewrite_asset_references_by_id(value: Any, urls_by_old_id: dict[uuid.UUID, str]) -> Any:
    """Repoint an imported page's asset references at the import's own assets."""
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if key in _ASSET_REFERENCE_ATTRIBUTES and isinstance(item, str):
                match = _ASSET_URL_PATTERN.fullmatch(item)
                if match is not None:
                    old_id = uuid.UUID(match.group("asset_id"))
                    if old_id in urls_by_old_id:
                        result[key] = urls_by_old_id[old_id]
                        continue
            result[key] = _rewrite_asset_references_by_id(item, urls_by_old_id)
        return result
    if isinstance(value, list):
        return [_rewrite_asset_references_by_id(item, urls_by_old_id) for item in value]
    return value


def _archive_error(rejection: ArchiveRejected) -> HTTPException:
    return HTTPException(
        status_code=rejection.status_code,
        detail={"code": rejection.code, "message": rejection.message},
    )


@router.post(
    "/modules/import", response_model=ModuleResponse, status_code=status.HTTP_201_CREATED
)
async def import_module(
    file: Annotated[UploadFile, File()],
    db: AsyncSession = Depends(get_db),
    author: User = Depends(require_content_manager),
    s3_client: S3Client = Depends(get_s3_client),
) -> ModuleResponse:
    """Bring a `.zip` export in as a fresh, unpublished draft.

    There is no import-and-publish path: whatever the archive says about a
    module's history, what lands here is a draft an author still has to
    review and publish for themselves.
    """
    settings = get_settings()
    data = await read_upload_within_cap(file, settings.import_max_archive_bytes)

    try:
        parsed = parse_export_archive(
            data,
            max_entries=settings.import_max_entries,
            max_compression_ratio=settings.import_max_compression_ratio,
            max_uncompressed_bytes=settings.import_max_uncompressed_bytes,
        )
    except ArchiveRejected as rejection:
        raise _archive_error(rejection) from rejection

    document = parsed.document
    if len(document.pages) > _MAX_PAGES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A module may hold at most {_MAX_PAGES} pages.",
        )

    # Every page validated — schema, size, nesting, and every attribute —
    # before anything is created. A rejection here must leave nothing behind.
    validated_pages: list[tuple[str, dict[str, Any]]] = []
    for page in document.pages:
        body, _search_text = validate_page_body(page.body, page.schema_version)
        validated_pages.append((page.title, body))

    # Every asset re-sniffed from its bytes and re-checked against the same
    # caps a fresh upload faces — the manifest's own claims about content
    # type and size are informational only, exactly as `kind` on a live
    # upload narrows the allowlist without ever relabelling the bytes.
    sniffed_assets: list[tuple[ExportedAsset, str, str]] = []
    total_asset_bytes = 0
    for asset in document.assets:
        raw = parsed.asset_bytes[asset.id]
        limit = (
            settings.asset_max_image_bytes
            if asset.kind == "image"
            else settings.asset_max_attachment_bytes
        )
        if len(raw) > limit:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail={
                    "code": "file_too_large",
                    "message": (
                        f"{asset.original_filename} is larger than the "
                        f"{limit // (1024 * 1024)} MB limit."
                    ),
                    "limit_bytes": limit,
                },
            )
        try:
            sniffed = sniff_upload(raw, kind=asset.kind, filename=asset.original_filename)
        except UploadRejected as rejection:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail={"code": rejection.code, "message": rejection.message},
            ) from rejection
        total_asset_bytes += len(raw)
        sniffed_assets.append((asset, sniffed.content_type, sniffed.filename))

    if total_asset_bytes > settings.asset_max_module_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail={
                "code": "module_quota_exceeded",
                "message": (
                    "This archive's assets exceed the module storage limit of "
                    f"{settings.asset_max_module_bytes // (1024 * 1024)} MB."
                ),
                "limit_bytes": settings.asset_max_module_bytes,
            },
        )

    group = ModuleTranslationGroup()
    db.add(group)
    await db.flush()

    module = Module(
        translation_group_id=group.id,
        language=document.language,
        title=document.title,
        description=document.description,
        estimated_duration_minutes=document.estimated_duration_minutes,
        created_by=author.id,
        last_edited_by=author.id,
    )
    db.add(module)
    await db.flush()
    group.primary_module_id = module.id

    # Assets before pages, same order `duplicate_module` uses and for the
    # same reason: the pages' own bodies need the new asset ids to rewrite
    # their `src`/`href` at, which do not exist until this loop creates them.
    urls_by_old_id: dict[uuid.UUID, str] = {}
    written_keys: list[str] = []
    try:
        for asset, content_type, filename in sniffed_assets:
            raw = parsed.asset_bytes[asset.id]
            new_id = uuid.uuid4()
            key = object_key(module.id, new_id)
            db.add(
                ModuleAsset(
                    id=new_id,
                    module_id=module.id,
                    kind=asset.kind,
                    object_key=key,
                    content_type=content_type,
                    size_bytes=len(raw),
                    original_filename=filename,
                    uploaded_by=author.id,
                )
            )
            await db.flush()
            await put_asset(
                s3_client,
                key=key,
                data=raw,
                content_type=content_type,
                download_filename=None if asset.kind == "image" else filename,
            )
            written_keys.append(key)
            urls_by_old_id[asset.id] = asset_url(module.id, new_id)
    except Exception:
        # Best effort: the object store cannot be rolled back by the
        # transaction the way the rows can, so a failure partway has to be
        # unwound by hand. The original failure is what the caller needs to
        # see, so a failure to clean up here must never replace it.
        for key in written_keys:
            try:
                await delete_asset(s3_client, key=key)
            except Exception:
                logger.exception("Could not remove an imported asset object: %s", key)
        raise

    for position, (title, body) in enumerate(validated_pages):
        rewritten = _rewrite_asset_references_by_id(body, urls_by_old_id)
        try:
            canonical = validate_document(rewritten)
        except DocumentValidationError as error:
            # A bug in the rewrite above, not something the archive did —
            # left to surface as one rather than dressed up as a 422, same
            # posture as `app.routes.content._duplicate_pages`.
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Could not re-validate an imported page after rewriting its assets.",
            ) from error
        db.add(
            ModulePage(
                module_id=module.id,
                position=position,
                title=title,
                body=canonical,
                schema_version=SCHEMA_VERSION,
                search_config=TEXT_SEARCH_CONFIGS[module.language],
                search_text=extract_search_text(canonical),
            )
        )

    await record_audit_log(
        db,
        actor_user_id=author.id,
        action="module_imported",
        detail={
            "module_id": str(module.id),
            "title": module.title,
            "page_count": len(validated_pages),
            "asset_count": len(sniffed_assets),
        },
    )
    await db.commit()
    await db.refresh(module)

    return await module_response(db, module)
