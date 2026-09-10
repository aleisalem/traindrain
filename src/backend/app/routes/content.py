import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.content import (
    CONSTRAINTS,
    SCHEMA_VERSION,
    TEXT_SEARCH_CONFIGS,
    DocumentValidationError,
    extract_search_text,
    validate_document,
)
from app.db import get_db
from app.dependencies import get_module_or_404, get_s3_client, require_content_manager
from app.models import (
    Module,
    ModuleAsset,
    ModuleEditSession,
    ModulePage,
    ModuleTranslationGroup,
    ModuleVersion,
    User,
)
from app.routes.assets import asset_url
from app.schemas.modules import (
    DuplicateRequest,
    ModuleActor,
    ModuleCreateRequest,
    ModuleEditorsResponse,
    ModuleResponse,
    ModuleUpdateRequest,
    PageCreateRequest,
    PageDeleteRequest,
    PageReorderRequest,
    PageResponse,
    PagesResponse,
    PageUpdateRequest,
    PublishRequest,
    RevisionKind,
    VersionResponse,
)
from app.security.audit import record_audit_log
from app.storage import S3Client, copy_asset, delete_asset, object_key

router = APIRouter(prefix="/api/content", tags=["content"])

logger = logging.getLogger(__name__)

_PAGE_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Page not found.")
_MAX_PAGES: int = CONSTRAINTS["limits"]["maxPagesPerModule"]

# How long after its last heartbeat an open editor still counts as present.
# Generous next to the client's 15-second beat, so a slow request or a
# backgrounded tab doesn't make a colleague flicker in and out of the list.
PRESENCE_WINDOW = timedelta(seconds=60)


async def _actors_by_id(db: AsyncSession, modules: list[Module]) -> dict[uuid.UUID, ModuleActor]:
    """Resolve every module's author and last editor in one query, not per row."""
    user_ids = {module.created_by for module in modules} | {
        module.last_edited_by for module in modules
    }
    if not user_ids:
        return {}
    users = (await db.execute(select(User).where(User.id.in_(user_ids)))).scalars()
    return {user.id: ModuleActor.from_user(user) for user in users}


async def _version_numbers(db: AsyncSession, modules: list[Module]) -> dict[uuid.UUID, int]:
    """Resolve every module's current version number in one query, not per row."""
    version_ids = {module.current_version_id for module in modules} - {None}
    if not version_ids:
        return {}
    rows = await db.execute(
        select(ModuleVersion.id, ModuleVersion.version_number).where(
            ModuleVersion.id.in_(version_ids)
        )
    )
    return {row.id: row.version_number for row in rows}


def _to_module_response(
    module: Module,
    actors: dict[uuid.UUID, ModuleActor],
    version_numbers: dict[uuid.UUID, int],
) -> ModuleResponse:
    return ModuleResponse(
        id=module.id,
        translation_group_id=module.translation_group_id,
        language=module.language,
        title=module.title,
        description=module.description,
        estimated_duration_minutes=module.estimated_duration_minutes,
        status=module.status,
        current_version_number=(
            version_numbers.get(module.current_version_id)
            if module.current_version_id
            else None
        ),
        created_by=actors[module.created_by],
        last_edited_by=actors[module.last_edited_by],
        created_at=module.created_at,
        updated_at=module.updated_at,
    )


async def _module_responses(db: AsyncSession, modules: list[Module]) -> list[ModuleResponse]:
    actors = await _actors_by_id(db, modules)
    version_numbers = await _version_numbers(db, modules)
    return [_to_module_response(module, actors, version_numbers) for module in modules]


async def _module_response(db: AsyncSession, module: Module) -> ModuleResponse:
    return (await _module_responses(db, [module]))[0]


async def _current_version_number(db: AsyncSession, module: Module) -> int | None:
    """The version number learners are reading, or `None` before the first publish."""
    if module.current_version_id is None:
        return None
    return (await _version_numbers(db, [module])).get(module.current_version_id)


async def _get_page(db: AsyncSession, module_id: uuid.UUID, page_id: uuid.UUID) -> ModulePage:
    # Scoped to the module in the URL, so a page id from another module is a
    # 404 rather than an edit applied to somebody else's material.
    page = (
        await db.execute(
            select(ModulePage).where(
                ModulePage.id == page_id, ModulePage.module_id == module_id
            )
        )
    ).scalar_one_or_none()
    if page is None:
        raise _PAGE_NOT_FOUND
    return page


@router.get("/modules", response_model=list[ModuleResponse])
async def list_modules(
    db: AsyncSession = Depends(get_db),
    author: User = Depends(require_content_manager),
) -> list[ModuleResponse]:
    modules = list(
        (await db.execute(select(Module).order_by(Module.created_at.desc()))).scalars()
    )
    return await _module_responses(db, modules)


@router.post("/modules", response_model=ModuleResponse, status_code=status.HTTP_201_CREATED)
async def create_module(
    payload: ModuleCreateRequest,
    db: AsyncSession = Depends(get_db),
    author: User = Depends(require_content_manager),
) -> ModuleResponse:
    # A standalone module still gets a translation group of its own, and is
    # nominated its primary. Assignment always targets the group, so adding a
    # translation later never rewrites an existing assignment.
    group = ModuleTranslationGroup()
    db.add(group)
    await db.flush()

    module = Module(
        translation_group_id=group.id,
        language=payload.language,
        title=payload.title,
        description=payload.description,
        estimated_duration_minutes=payload.estimated_duration_minutes,
        # Never taken from the client — the acting session is the only source.
        created_by=author.id,
        last_edited_by=author.id,
    )
    db.add(module)
    await db.flush()

    group.primary_module_id = module.id

    await record_audit_log(
        db,
        actor_user_id=author.id,
        action="module_created",
        detail={
            "module_id": str(module.id),
            "translation_group_id": str(group.id),
            "title": module.title,
            "language": module.language,
        },
    )
    await db.commit()
    await db.refresh(module)

    return await _module_response(db, module)


@router.get("/modules/{module_id}", response_model=ModuleResponse)
async def get_module(
    module_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    author: User = Depends(require_content_manager),
) -> ModuleResponse:
    module = await get_module_or_404(db, module_id)
    return await _module_response(db, module)


@router.patch("/modules/{module_id}", response_model=ModuleResponse)
async def update_module(
    module_id: uuid.UUID,
    payload: ModuleUpdateRequest,
    db: AsyncSession = Depends(get_db),
    author: User = Depends(require_content_manager),
) -> ModuleResponse:
    module = await get_module_or_404(db, module_id)

    # exclude_unset, so a field the client left out keeps its stored value
    # while an explicitly-null one is genuinely cleared.
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(module, field, value)
    module.last_edited_by = author.id

    await record_audit_log(
        db,
        actor_user_id=author.id,
        action="module_updated",
        detail={
            "module_id": str(module.id),
            "title": module.title,
            "fields": sorted(changes),
        },
    )
    await db.commit()
    await db.refresh(module)

    return await _module_response(db, module)


# --- Page authoring -------------------------------------------------------
#
# Every mutation here is a *draft* mutation: it changes `module_pages`, which
# is the working draft. Publishing (and therefore what a learner reads) is a
# separate action that arrives with version snapshots.


def _claim_draft(module: Module, draft_revision: int, author: User) -> None:
    """Take the draft's optimistic lock, or refuse with a clear conflict.

    Two Content Managers may edit the same module — there is no ownership —
    so the second write of a pair has to fail loudly rather than overwrite an
    edit the first one has already saved.
    """
    if module.draft_revision != draft_revision:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "draft_conflict",
                "message": (
                    "This module was edited by someone else since you loaded it. "
                    "Reload the page to see their changes."
                ),
                "draft_revision": module.draft_revision,
            },
        )
    module.draft_revision += 1
    module.last_edited_by = author.id


def _validated_body(body: Any, schema_version: int) -> tuple[dict[str, Any], str]:
    """Validate a submitted page body, or raise the 422 that refuses it."""
    if schema_version != SCHEMA_VERSION:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "schema_version_mismatch",
                "message": (
                    f"This document was written for schema version {schema_version}; "
                    f"this server speaks version {SCHEMA_VERSION}."
                ),
            },
        )
    try:
        document = validate_document(body)
    except DocumentValidationError as error:
        # Rejected, never sanitized and accepted.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": error.code, "message": error.message},
        ) from error
    return document, extract_search_text(document)


async def _module_pages(db: AsyncSession, module_id: uuid.UUID) -> list[ModulePage]:
    return list(
        (
            await db.execute(
                select(ModulePage)
                .where(ModulePage.module_id == module_id)
                .order_by(ModulePage.position)
            )
        ).scalars()
    )


def _to_page_response(page: ModulePage) -> PageResponse:
    return PageResponse(
        id=page.id,
        position=page.position,
        title=page.title,
        schema_version=page.schema_version,
        body=page.body,
        updated_at=page.updated_at,
    )


async def _pages_response(db: AsyncSession, module: Module) -> PagesResponse:
    pages = await _module_pages(db, module.id)
    return PagesResponse(
        draft_revision=module.draft_revision,
        schema_version=SCHEMA_VERSION,
        pages=[_to_page_response(page) for page in pages],
    )


@router.get("/modules/{module_id}/pages", response_model=PagesResponse)
async def list_pages(
    module_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    author: User = Depends(require_content_manager),
) -> PagesResponse:
    module = await get_module_or_404(db, module_id)
    return await _pages_response(db, module)


@router.post(
    "/modules/{module_id}/pages",
    response_model=PagesResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_page(
    module_id: uuid.UUID,
    payload: PageCreateRequest,
    db: AsyncSession = Depends(get_db),
    author: User = Depends(require_content_manager),
) -> PagesResponse:
    module = await get_module_or_404(db, module_id, for_update=True)
    document, search_text = _validated_body(payload.body, payload.schema_version)

    page_count = (
        await db.execute(
            select(func.count())
            .select_from(ModulePage)
            .where(ModulePage.module_id == module.id)
        )
    ).scalar_one()
    if page_count >= _MAX_PAGES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A module may hold at most {_MAX_PAGES} pages.",
        )

    _claim_draft(module, payload.draft_revision, author)

    db.add(
        ModulePage(
            module_id=module.id,
            position=page_count,
            title=payload.title,
            body=document,
            schema_version=SCHEMA_VERSION,
            # From the module's stored language, so German content is stemmed
            # with German rules — never guessed from the text at query time.
            search_config=TEXT_SEARCH_CONFIGS[module.language],
            search_text=search_text,
        )
    )
    await db.commit()
    return await _pages_response(db, module)


@router.post("/modules/{module_id}/pages/reorder", response_model=PagesResponse)
async def reorder_pages(
    module_id: uuid.UUID,
    payload: PageReorderRequest,
    db: AsyncSession = Depends(get_db),
    author: User = Depends(require_content_manager),
) -> PagesResponse:
    module = await get_module_or_404(db, module_id, for_update=True)
    pages = await _module_pages(db, module.id)
    by_id = {page.id: page for page in pages}

    # A permutation of exactly this module's pages, or nothing — a partial
    # order would leave the remaining pages without a defined position.
    if len(payload.page_ids) != len(set(payload.page_ids)) or set(payload.page_ids) != set(by_id):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="A reorder must list every page of this module exactly once.",
        )

    _claim_draft(module, payload.draft_revision, author)

    # One transaction, and the (module_id, position) constraint is DEFERRABLE,
    # so the renumbering is checked once at commit rather than row by row.
    for position, page_id in enumerate(payload.page_ids):
        by_id[page_id].position = position
    await db.commit()
    return await _pages_response(db, module)


@router.patch("/modules/{module_id}/pages/{page_id}", response_model=PagesResponse)
async def update_page(
    module_id: uuid.UUID,
    page_id: uuid.UUID,
    payload: PageUpdateRequest,
    db: AsyncSession = Depends(get_db),
    author: User = Depends(require_content_manager),
) -> PagesResponse:
    module = await get_module_or_404(db, module_id, for_update=True)
    page = await _get_page(db, module.id, page_id)

    validated: tuple[dict[str, Any], str] | None = None
    if payload.body is not None:
        if payload.schema_version is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="A page body must be sent with its `schema_version`.",
            )
        validated = _validated_body(payload.body, payload.schema_version)

    _claim_draft(module, payload.draft_revision, author)

    if payload.title is not None:
        page.title = payload.title
    if validated is not None:
        page.body, page.search_text = validated
        page.schema_version = SCHEMA_VERSION
        page.search_config = TEXT_SEARCH_CONFIGS[module.language]

    await db.commit()
    return await _pages_response(db, module)


@router.delete("/modules/{module_id}/pages/{page_id}", response_model=PagesResponse)
async def delete_page(
    module_id: uuid.UUID,
    page_id: uuid.UUID,
    payload: PageDeleteRequest,
    db: AsyncSession = Depends(get_db),
    author: User = Depends(require_content_manager),
) -> PagesResponse:
    module = await get_module_or_404(db, module_id, for_update=True)
    page = await _get_page(db, module.id, page_id)

    _claim_draft(module, payload.draft_revision, author)

    await db.delete(page)
    await db.flush()

    # Positions stay contiguous from 0, so "page 3 of 7" never has a gap.
    for position, remaining in enumerate(await _module_pages(db, module.id)):
        remaining.position = position

    await db.commit()
    return await _pages_response(db, module)


# --- Publishing -----------------------------------------------------------
#
# The line between what an author is working on and what a learner reads.
#
# `module_pages` is always the draft, whatever the module's status. Publishing
# freezes a copy of it into an immutable `module_versions` row and repoints
# `current_version_id` at that row, so a revision to a live module is invisible
# until the author says otherwise — and so a completion record can later name
# exactly which text somebody read, rather than pointing at material that has
# moved on since.


def _build_snapshot(module: Module, pages: list[ModulePage]) -> dict[str, Any]:
    """Everything a learner reads at this version, frozen.

    Page ids travel into the snapshot because ticket 5's progress tracking
    records which pages a learner has seen: those ids have to mean the same
    thing on the next request, and a position in an array would not survive the
    author reordering the draft underneath them.
    """
    return {
        "schema_version": SCHEMA_VERSION,
        "title": module.title,
        "description": module.description,
        "language": module.language,
        "estimated_duration_minutes": module.estimated_duration_minutes,
        "pages": [
            {
                "id": str(page.id),
                "position": page.position,
                "title": page.title,
                "schema_version": page.schema_version,
                "body": page.body,
            }
            for page in pages
        ],
    }


@router.post("/modules/{module_id}/publish", response_model=ModuleResponse)
async def publish_module(
    module_id: uuid.UUID,
    payload: PublishRequest,
    db: AsyncSession = Depends(get_db),
    author: User = Depends(require_content_manager),
) -> ModuleResponse:
    """Freeze the draft into a new version and point learners at it.

    `revision_kind` is required — see `PublishRequest`. Recording it is all
    this ticket does with it; ticket 7 is where `substantive` starts dragging
    completed learners back through the material, once there is an assignment
    to scope that to.
    """
    # The row lock is what makes version numbering safe: two simultaneous
    # publishes would otherwise both read "the highest version is 2" and both
    # try to write a 3.
    module = await get_module_or_404(db, module_id, for_update=True)
    pages = await _module_pages(db, module.id)
    if not pages:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "empty_module",
                "message": "Add at least one page before publishing this module.",
            },
        )

    highest = (
        await db.execute(
            select(func.coalesce(func.max(ModuleVersion.version_number), 0)).where(
                ModuleVersion.module_id == module.id
            )
        )
    ).scalar_one()

    version = ModuleVersion(
        module_id=module.id,
        version_number=highest + 1,
        published_by=author.id,
        revision_kind=payload.revision_kind,
        snapshot=_build_snapshot(module, pages),
    )
    db.add(version)
    await db.flush()

    module.status = "published"
    module.current_version_id = version.id

    await record_audit_log(
        db,
        actor_user_id=author.id,
        action="module_published",
        detail={
            "module_id": str(module.id),
            "title": module.title,
            "version_number": version.version_number,
            "revision_kind": version.revision_kind,
            "page_count": len(pages),
        },
    )
    await db.commit()
    await db.refresh(module)
    return await _module_response(db, module)


@router.post("/modules/{module_id}/unpublish", response_model=ModuleResponse)
async def unpublish_module(
    module_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    author: User = Depends(require_content_manager),
) -> ModuleResponse:
    """Take a module out of circulation without destroying anything.

    Reversible by design, and the opposite of ticket 11's delete: no page, no
    version, and no stored file is touched. `current_version_id` deliberately
    keeps pointing at the last published version, so a completion record
    against it still resolves while the module is out of circulation.

    Republishing is an ordinary publish, not a restore: it snapshots the draft
    as it stands now and writes the next version. That is the safe direction —
    flipping the status back would silently publish whatever was written to the
    draft in the meantime, under a version number that predates it.
    """
    module = await get_module_or_404(db, module_id, for_update=True)
    if module.status != "published":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "not_published",
                "message": "This module is not published.",
            },
        )

    module.status = "draft"
    version_number = await _current_version_number(db, module)

    await record_audit_log(
        db,
        actor_user_id=author.id,
        action="module_unpublished",
        detail={
            "module_id": str(module.id),
            "title": module.title,
            "version_number": version_number,
        },
    )
    await db.commit()
    await db.refresh(module)
    return await _module_response(db, module)


# The attributes a page body can point at an asset with. `src` is an embedded
# image; `href` is a link to one, which the schema permits because an asset URL
# is a site-relative path — the assets panel shows the author exactly that URL,
# so a page linking a policy PDF is ordinary authored content, not an edge case.
_ASSET_REFERENCE_ATTRIBUTES = frozenset({"src", "href"})


def _rewrite_asset_references(value: Any, urls: dict[str, str]) -> Any:
    """Repoint a copied page's asset references at the copy's own assets.

    A duplicate owns its own asset rows and its own stored objects, so leaving
    the copied pages pointing at the original's would make the two modules
    share files — and deleting the original would then silently empty the
    copy's pages and break its links. Matched against the exact URLs of the
    source module's own assets, so nothing else in the tree that happens to
    look like a path is touched.
    """
    if isinstance(value, dict):
        return {
            key: urls[item]
            if key in _ASSET_REFERENCE_ATTRIBUTES and isinstance(item, str) and item in urls
            else _rewrite_asset_references(item, urls)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_rewrite_asset_references(item, urls) for item in value]
    return value


async def _duplicate_assets(
    db: AsyncSession,
    s3_client: S3Client,
    *,
    source: Module,
    copy: Module,
    author: User,
) -> dict[str, str]:
    """Give the copy its own asset rows and its own stored objects.

    Returns the source's asset URLs mapped to the copy's, for rewriting the
    page bodies with.
    """
    source_assets = (
        await db.execute(
            select(ModuleAsset)
            .where(ModuleAsset.module_id == source.id)
            .order_by(ModuleAsset.created_at)
        )
    ).scalars()

    asset_urls: dict[str, str] = {}
    object_copies: list[tuple[str, str]] = []
    for asset in source_assets:
        new_id = uuid.uuid4()
        key = object_key(copy.id, new_id)
        db.add(
            ModuleAsset(
                id=new_id,
                module_id=copy.id,
                kind=asset.kind,
                object_key=key,
                # The sniffer already decided what these bytes are, when the
                # original was accepted. Re-deriving it here would be a second,
                # weaker answer to a settled question.
                content_type=asset.content_type,
                size_bytes=asset.size_bytes,
                original_filename=asset.original_filename,
                uploaded_by=author.id,
            )
        )
        asset_urls[asset_url(source.id, asset.id)] = asset_url(copy.id, new_id)
        object_copies.append((asset.object_key, key))
    await db.flush()

    copied: list[str] = []
    try:
        for source_key, key in object_copies:
            # Before the commit, as everywhere else assets are written: if the
            # store refuses, the transaction rolls back and no row is left
            # describing an object that was never created.
            await copy_asset(s3_client, source_key=source_key, key=key)
            copied.append(key)
    except Exception:
        # The rollback undoes the rows, but it cannot reach into the object
        # store — so the objects already written have to be taken back by hand,
        # or a failed duplicate leaves a private bucket accumulating files
        # nothing can enumerate. Best effort: the original failure is what the
        # caller needs to see, so a failure to clean up must not replace it.
        for key in copied:
            try:
                await delete_asset(s3_client, key=key)
            except Exception:
                logger.exception("Could not remove a copied asset object: %s", key)
        raise

    return asset_urls


async def _duplicate_pages(db: AsyncSession, *, source: Module, copy: Module, urls: dict[str, str]) -> None:
    """Copy the source's pages, repointed at the copy's own assets."""
    for page in await _module_pages(db, source.id):
        # Re-validated, so the invariant that everything in `module_pages` has
        # been through the validator holds on this path too, and what is stored
        # is the validator's canonical document exactly as on the write path. A
        # failure here is a bug in the rewrite above, not something a client
        # did, so it is left to surface as one rather than dressed up as a 422.
        body = validate_document(_rewrite_asset_references(page.body, urls))
        db.add(
            ModulePage(
                module_id=copy.id,
                position=page.position,
                title=page.title,
                body=body,
                schema_version=page.schema_version,
                search_config=page.search_config,
                search_text=page.search_text,
            )
        )


@router.post(
    "/modules/{module_id}/duplicate",
    response_model=ModuleResponse,
    status_code=status.HTTP_201_CREATED,
)
async def duplicate_module(
    module_id: uuid.UUID,
    payload: DuplicateRequest,
    db: AsyncSession = Depends(get_db),
    author: User = Depends(require_content_manager),
    s3_client: S3Client = Depends(get_s3_client),
) -> ModuleResponse:
    """A fresh, independent draft based on material that already works.

    Independent in every direction: its own translation group (so it is not a
    language variant of the original), its own pages, and its own copies of the
    stored asset objects. Nothing the author does to the copy can reach back
    into the original, which is the whole point of duplicating rather than
    editing.
    """
    source = await get_module_or_404(db, module_id)

    group = ModuleTranslationGroup()
    db.add(group)
    await db.flush()

    copy = Module(
        translation_group_id=group.id,
        # Fixed at creation on the original and fixed here too: the copy's
        # pages are indexed under the same text-search configuration.
        language=source.language,
        title=payload.title or source.title,
        description=source.description,
        estimated_duration_minutes=source.estimated_duration_minutes,
        created_by=author.id,
        last_edited_by=author.id,
    )
    db.add(copy)
    await db.flush()
    group.primary_module_id = copy.id

    asset_urls = await _duplicate_assets(
        db, s3_client, source=source, copy=copy, author=author
    )
    await _duplicate_pages(db, source=source, copy=copy, urls=asset_urls)

    await record_audit_log(
        db,
        actor_user_id=author.id,
        action="module_duplicated",
        detail={
            "module_id": str(copy.id),
            "source_module_id": str(source.id),
            "title": copy.title,
            "language": copy.language,
        },
    )
    await db.commit()
    await db.refresh(copy)
    return await _module_response(db, copy)


@router.get("/modules/{module_id}/versions", response_model=list[VersionResponse])
async def list_versions(
    module_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    author: User = Depends(require_content_manager),
) -> list[VersionResponse]:
    """A module's publish history, newest first."""
    module = await get_module_or_404(db, module_id)
    versions = list(
        (
            await db.execute(
                select(ModuleVersion)
                .where(ModuleVersion.module_id == module.id)
                .order_by(ModuleVersion.version_number.desc())
            )
        ).scalars()
    )

    publisher_ids = {version.published_by for version in versions}
    publishers: dict[uuid.UUID, ModuleActor] = {}
    if publisher_ids:
        users = (await db.execute(select(User).where(User.id.in_(publisher_ids)))).scalars()
        publishers = {user.id: ModuleActor.from_user(user) for user in users}

    return [
        VersionResponse(
            id=version.id,
            version_number=version.version_number,
            # The row's CHECK constraint is what makes this narrowing sound;
            # nothing else can have been written.
            revision_kind=cast(RevisionKind, version.revision_kind),
            published_at=version.published_at,
            published_by=publishers[version.published_by],
            title=version.snapshot.get("title", ""),
            page_count=len(version.snapshot.get("pages", [])),
        )
        for version in versions
    ]


# --- Presence -------------------------------------------------------------
#
# Concurrent editing of a module's *metadata* is deliberately allowed rather
# than locked: an author who has to be told "someone else saved first, reload
# and retype" on a title change is being punished for a collision the system
# could simply have shown them coming. Page bodies are different — those keep
# the hard `draft_revision` conflict above, because losing a page of written
# material is not a recoverable annoyance.
#
# So the trade here is: make the collision visible before it happens, warn at
# the moment of saving, and then let the author decide.


async def _current_editors(
    db: AsyncSession, module_id: uuid.UUID, *, excluding: uuid.UUID
) -> list[ModuleActor]:
    cutoff = datetime.now(UTC) - PRESENCE_WINDOW
    rows = (
        await db.execute(
            select(ModuleEditSession.user_id).where(
                ModuleEditSession.module_id == module_id,
                ModuleEditSession.last_seen_at >= cutoff,
                ModuleEditSession.user_id != excluding,
            )
        )
    ).scalars()
    user_ids = list(rows)
    if not user_ids:
        return []

    users = (await db.execute(select(User).where(User.id.in_(user_ids)))).scalars()
    return sorted(
        (ModuleActor.from_user(user) for user in users),
        key=lambda actor: actor.display_name.lower(),
    )


@router.post("/modules/{module_id}/editing", response_model=ModuleEditorsResponse)
async def heartbeat_editing(
    module_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    author: User = Depends(require_content_manager),
) -> ModuleEditorsResponse:
    """Record that the caller has this module open, and say who else does.

    One endpoint rather than two because this is one operation from the
    screen's point of view — a presence ping — and splitting it would double
    the traffic of something that runs on a timer.
    """
    module = await get_module_or_404(db, module_id)

    now = datetime.now(UTC)
    await db.execute(
        pg_insert(ModuleEditSession)
        .values(module_id=module.id, user_id=author.id, last_seen_at=now)
        .on_conflict_do_update(
            index_elements=["module_id", "user_id"], set_={"last_seen_at": now}
        )
    )
    # Rows that stopped being refreshed are dead weight; clearing them here
    # keeps the table proportional to who is actually editing, with no
    # scheduled job to own.
    await db.execute(
        delete(ModuleEditSession).where(
            ModuleEditSession.module_id == module.id,
            ModuleEditSession.last_seen_at < now - PRESENCE_WINDOW,
        )
    )
    await db.commit()

    return ModuleEditorsResponse(
        editors=await _current_editors(db, module.id, excluding=author.id)
    )


@router.delete("/modules/{module_id}/editing", status_code=status.HTTP_204_NO_CONTENT)
async def stop_editing(
    module_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    author: User = Depends(require_content_manager),
) -> None:
    """Leave the module, so the other authors see it immediately.

    Deliberately forgiving: closing an editor you were not registered in is
    not an error, because this is called on unmount and must never turn into
    a failure the author has to care about.
    """
    await db.execute(
        delete(ModuleEditSession).where(
            ModuleEditSession.module_id == module_id,
            ModuleEditSession.user_id == author.id,
        )
    )
    await db.commit()
