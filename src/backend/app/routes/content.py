import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import case, delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.access import ensure_module_editable
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
    Assignment,
    Module,
    ModuleAsset,
    ModuleEditSession,
    ModulePage,
    ModuleProgress,
    ModuleTranslationGroup,
    ModuleVersion,
    Tag,
    User,
)
from app.routes.assets import asset_url
from app.schemas.modules import (
    DeletionImpactResponse,
    DuplicateRequest,
    LinkVariantRequest,
    ModuleActor,
    ModuleCreateRequest,
    ModuleEditorsResponse,
    ModuleLanguage,
    ModuleResponse,
    ModuleUpdateRequest,
    PageCreateRequest,
    PageDeleteRequest,
    PageReorderRequest,
    PageResponse,
    PagesResponse,
    PageUpdateRequest,
    PublishRequest,
    RevisionImpactResponse,
    RevisionKind,
    SetPrimaryVariantRequest,
    TranslationGroupResponse,
    VersionResponse,
)
from app.search import (
    apply_tag_filter,
    get_or_create_tags,
    module_search_predicate,
    normalize_tag_filter,
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
        catalog_visible=module.catalog_visible,
        current_version_number=(
            version_numbers.get(module.current_version_id)
            if module.current_version_id
            else None
        ),
        deleted_version_number=module.deleted_version_number,
        tags=sorted(tag.name for tag in module.tags),
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


@router.get("/tags", response_model=list[str])
async def list_tags(
    db: AsyncSession = Depends(get_db),
    author: User = Depends(require_content_manager),
) -> list[str]:
    """Every tag in use, for the authoring screen's autocomplete."""
    rows = (await db.execute(select(Tag.name).order_by(Tag.name))).scalars()
    return list(rows)


@router.get("/modules", response_model=list[ModuleResponse])
async def list_modules(
    q: str | None = Query(default=None, min_length=1, max_length=200),
    language: ModuleLanguage | None = Query(default=None),
    status_filter: Literal["draft", "published"] | None = Query(default=None, alias="status"),
    tags: list[str] | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    author: User = Depends(require_content_manager),
) -> list[ModuleResponse]:
    statement = select(Module).order_by(Module.created_at.desc())
    if language is not None:
        statement = statement.where(Module.language == language)
    if status_filter is not None:
        statement = statement.where(Module.status == status_filter)
    else:
        # A deleted module's tombstone survives for its completion records,
        # not for authoring — nothing here should list it back among drafts
        # and published material. There is deliberately no `status=deleted`
        # filter value to ask for it with; a tombstone is reached by the id a
        # completion record or an audit entry already names, not browsed to.
        statement = statement.where(Module.status != "deleted")
    if q:
        statement = statement.where(module_search_predicate(q))
    statement = apply_tag_filter(statement, normalize_tag_filter(tags))

    modules = list((await db.execute(statement)).scalars())
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
    ensure_module_editable(module)

    # exclude_unset, so a field the client left out keeps its stored value
    # while an explicitly-null one is genuinely cleared.
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        # `tags` isn't a plain column — it's the module's whole tag set,
        # resolved against `tags` below rather than assigned directly.
        if field == "tags":
            continue
        setattr(module, field, value)
    if "tags" in changes:
        module.tags = await get_or_create_tags(db, changes["tags"])
    # Putting a module on the catalog, or taking it off, is a decision about
    # circulation rather than about the text. Recording it as "last edited by"
    # would put an author's name against words they did not write.
    if changes.keys() - {"catalog_visible"}:
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
    ensure_module_editable(module)
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
    ensure_module_editable(module)
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
    ensure_module_editable(module)
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
    ensure_module_editable(module)
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


async def _learner_counts(db: AsyncSession, module: Module) -> tuple[int, int]:
    """(completed, in progress) learners for this module's body of material.

    Scoped to the translation group rather than this one variant, because
    `module_progress` is: a learner has one record per body of material however
    many language variants of it exist.
    """
    row = (
        await db.execute(
            select(
                func.count().filter(ModuleProgress.completed_at.is_not(None)),
                func.count().filter(ModuleProgress.completed_at.is_(None)),
            ).where(ModuleProgress.translation_group_id == module.translation_group_id)
        )
    ).one()
    return int(row[0]), int(row[1])


async def _send_learners_back(db: AsyncSession, module: Module) -> int:
    """Put every learner of this material back at the start of it.

    What a `substantive` revision means, made real. Two things happen, and both
    are needed:

    * `superseded_at` is stamped on completed rows, so a finished learner sees
      the module as outstanding again. `completed_at` and
      `completed_version_number` are deliberately **left alone** — the person
      did read v2 on that date, and a record that erased it would be lying
      about the past to describe the present.
    * `pages_viewed` is emptied and `current_page_id` cleared, for completed and
      part-read learners alike. This is the half that makes the obligation real.
      A page keeps its id across an edit, so a v2 reader's viewed-page ids still
      name every page of v3 — leaving them in place would re-open the
      attestation while the "read every page first" check was already satisfied,
      and the learner could confirm having read changed material by clicking
      once on the last page. The array is the evidence that check rests on, so a
      substantive rewrite has to invalidate it.

    Returns the number of completions superseded, for the audit entry.

    Every learner of the group is reset, not only the completed ones: somebody
    nine pages into v2 has read nine pages that no longer exist in the form they
    read them, and letting those count towards attesting to v3 is the same hole
    by a quieter route.
    """
    superseded_at = datetime.now(UTC)
    rows = await db.execute(
        update(ModuleProgress)
        .where(ModuleProgress.translation_group_id == module.translation_group_id)
        .values(
            pages_viewed=[],
            current_page_id=None,
            superseded_at=case(
                (ModuleProgress.completed_at.is_not(None), superseded_at),
                # Never completed, so there is no completion to supersede.
                else_=None,
            ),
        )
        # No ORM state to keep in step: nothing in this request loaded a
        # progress row, and the learner reading one holds their own session.
        .execution_options(synchronize_session=False)
        .returning(ModuleProgress.completed_at)
    )
    return sum(1 for (completed_at,) in rows if completed_at is not None)


@router.get(
    "/modules/{module_id}/revision-impact", response_model=RevisionImpactResponse
)
async def get_revision_impact(
    module_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    author: User = Depends(require_content_manager),
) -> RevisionImpactResponse:
    """How many people a substantive publish of this module would affect.

    Asked by the publish dialog while the author is still choosing between
    `minor` and `substantive`. A read, and a snapshot: a learner may finish the
    module between this call and the publish, so the number is what the choice
    looks like now, not a promise about what the publish will do.
    """
    module = await get_module_or_404(db, module_id)
    completed, in_progress = await _learner_counts(db, module)
    return RevisionImpactResponse(
        completed_learners=completed, in_progress_learners=in_progress
    )


@router.post("/modules/{module_id}/publish", response_model=ModuleResponse)
async def publish_module(
    module_id: uuid.UUID,
    payload: PublishRequest,
    db: AsyncSession = Depends(get_db),
    author: User = Depends(require_content_manager),
) -> ModuleResponse:
    """Freeze the draft into a new version and point learners at it.

    `revision_kind` is required — see `PublishRequest` — and it is acted on
    here, not merely recorded. A `minor` publish leaves every learner exactly
    where they are. A `substantive` one sends them back through the material:
    see `_send_learners_back` for what that costs and why both halves of it are
    necessary.

    The scope is every learner of the module's translation group. Once
    assignments exist (ticket 7), a substantive publish will still supersede all
    of them — an assignment decides who is *told* to read something, not whose
    completion of it is still current.
    """
    # The row lock is what makes version numbering safe: two simultaneous
    # publishes would otherwise both read "the highest version is 2" and both
    # try to write a 3.
    module = await get_module_or_404(db, module_id, for_update=True)
    ensure_module_editable(module)
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

    # After `current_version_id` is repointed: a learner whose attestation is
    # racing this publish takes the progress row's lock either before this runs
    # (and completes against the old version, which the reset then supersedes)
    # or after it (and finds an emptied `pages_viewed`, so they are asked to
    # read the new text). Both orders end with the new version unattested.
    superseded = (
        await _send_learners_back(db, module)
        if payload.revision_kind == "substantive"
        else 0
    )

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
            # The blast radius, recorded where it can be answered for later.
            "superseded_completions": superseded,
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


async def _completion_count(db: AsyncSession, translation_group_id: uuid.UUID) -> int:
    """How many learners have ever completed this material.

    Counted over the whole translation group, like every other learner count in
    this file — one `ModuleProgress` row is one person's progress on the body of
    material, whichever language variant they happened to read. Includes
    superseded completions: a substantive republish marks one outstanding again
    but never erases `completed_at`, and it is still evidence a delete's
    tombstone has to go on carrying.
    """
    return (
        await db.execute(
            select(func.count())
            .select_from(ModuleProgress)
            .where(
                ModuleProgress.translation_group_id == translation_group_id,
                ModuleProgress.completed_at.is_not(None),
            )
        )
    ).scalar_one()


@router.get(
    "/modules/{module_id}/deletion-impact", response_model=DeletionImpactResponse
)
async def get_deletion_impact(
    module_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    author: User = Depends(require_content_manager),
) -> DeletionImpactResponse:
    """How many completion records a delete's tombstone would carry.

    Asked by the confirmation dialog while the decision is still avoidable —
    the same "tell the author the number before they commit" shape
    `get_revision_impact` already gives the publish dialog.
    """
    module = await get_module_or_404(db, module_id)
    return DeletionImpactResponse(
        completion_count=await _completion_count(db, module.translation_group_id)
    )


@router.delete("/modules/{module_id}", response_model=ModuleResponse)
async def delete_module(
    module_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    author: User = Depends(require_content_manager),
    s3_client: S3Client = Depends(get_s3_client),
) -> ModuleResponse:
    """Content that must not exist any more, genuinely gone.

    Modelled directly on Release 0's user-erase tombstone: the row survives —
    `title`, `language`, and its timestamps stay, so a completion record still
    resolves and can render as *"Phishing Awareness — deleted"* — but every
    page, every version snapshot, and every stored asset object is destroyed,
    and every assignment naming this material is removed, so it can never be
    newly assigned again. `deleted` is terminal: `ensure_module_editable`
    refuses every other mutating authoring route from here on.

    Progress rows are deliberately left untouched. They are a learner's own
    record of what they read, not the author's content, and the whole point of
    a tombstone is that the evidence outlives what it is evidence of.
    """
    module = await get_module_or_404(db, module_id, for_update=True)
    if module.status == "deleted":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "already_deleted",
                "message": "This module has already been deleted.",
            },
        )

    affected = await _completion_count(db, module.translation_group_id)

    assets = list(
        (
            await db.execute(select(ModuleAsset).where(ModuleAsset.module_id == module.id))
        ).scalars()
    )
    for asset in assets:
        # Row first, then the object — the same order `delete_module_asset`
        # uses and for the same reason: if the store refuses, the transaction
        # rolls back and the row survives alongside the object it describes,
        # rather than an object already gone for real outliving a row a later
        # failure in this loop put back.
        await db.delete(asset)
        await db.flush()
        await delete_asset(s3_client, key=asset.object_key)

    await db.execute(delete(ModulePage).where(ModulePage.module_id == module.id))

    # Captured before it is cleared: the tombstone's own memory of what
    # version it was on, independent of any one learner's
    # `completed_version_number` — a module nobody has completed still gets
    # to say "last published as version N" rather than nothing at all.
    module.deleted_version_number = await _current_version_number(db, module)

    # Cleared explicitly, ahead of the version rows going, rather than left to
    # the FK's `ON DELETE SET NULL` to do implicitly — so the in-memory module
    # never disagrees with what the database is about to make true.
    module.current_version_id = None
    await db.flush()
    await db.execute(delete(ModuleVersion).where(ModuleVersion.module_id == module.id))

    # Scoped to the translation group, like every assignment already is: this
    # variant's material can no longer be assigned, and neither can any
    # sibling's, because they are all the same assignable unit.
    await db.execute(
        delete(Assignment).where(Assignment.translation_group_id == module.translation_group_id)
    )

    module.status = "deleted"
    module.deleted_at = datetime.now(UTC)
    module.catalog_visible = False
    module.last_edited_by = author.id

    await record_audit_log(
        db,
        actor_user_id=author.id,
        action="module_deleted",
        detail={
            "module_id": str(module.id),
            "translation_group_id": str(module.translation_group_id),
            "title": module.title,
            "affected_completions": affected,
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
    ensure_module_editable(source)

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


# --- Translations -----------------------------------------------------------
#
# A translation group is the body of material; a module is one language's text
# of it. Every module already belongs to one (ticket 1) — what this adds is a
# way to declare that two modules that were each authored standalone are, in
# fact, the same material in two languages, and to say which one a learner
# whose language is neither gets.


async def _group_or_404(db: AsyncSession, group_id: uuid.UUID) -> ModuleTranslationGroup:
    group = await db.get(ModuleTranslationGroup, group_id)
    if group is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Translation group not found."
        )
    return group


async def _group_variants(db: AsyncSession, group_id: uuid.UUID) -> list[Module]:
    return list(
        (
            await db.execute(
                select(Module)
                .where(Module.translation_group_id == group_id)
                .order_by(Module.language)
            )
        ).scalars()
    )


async def _translation_group_response(
    db: AsyncSession, group: ModuleTranslationGroup
) -> TranslationGroupResponse:
    variants = await _group_variants(db, group.id)
    return TranslationGroupResponse(
        id=group.id,
        primary_module_id=group.primary_module_id,
        variants=await _module_responses(db, variants),
    )


@router.get("/translation-groups/{group_id}", response_model=TranslationGroupResponse)
async def get_translation_group(
    group_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    author: User = Depends(require_content_manager),
) -> TranslationGroupResponse:
    group = await _group_or_404(db, group_id)
    return await _translation_group_response(db, group)


@router.post(
    "/translation-groups/{group_id}/variants",
    response_model=TranslationGroupResponse,
    status_code=status.HTTP_201_CREATED,
)
async def link_variant(
    group_id: uuid.UUID,
    payload: LinkVariantRequest,
    db: AsyncSession = Depends(get_db),
    author: User = Depends(require_content_manager),
) -> TranslationGroupResponse:
    """Declare an existing module a translation of this group's material.

    The source has to be genuinely standalone — the only module in its own
    group — because linking it here would otherwise orphan whatever else it was
    already grouped with. And it has to be untouched by any learner yet: a
    completion is keyed on the translation group it was read under, and moving
    the module out from under that group would strand that history behind a
    group it no longer belongs to, unrecoverably.
    """
    await _group_or_404(db, group_id)
    # Locked so a concurrent link of the same source cannot pass every check
    # below before either has committed.
    source = await get_module_or_404(db, payload.module_id, for_update=True)

    if source.translation_group_id == group_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "already_a_variant",
                "message": "This module is already a variant of this group.",
            },
        )
    if source.status == "deleted":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "module_deleted",
                "message": "A deleted module cannot be linked as a translation.",
            },
        )

    sibling_count = (
        await db.execute(
            select(func.count())
            .select_from(Module)
            .where(Module.translation_group_id == source.translation_group_id)
        )
    ).scalar_one()
    if sibling_count > 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "source_not_standalone",
                "message": "This module is already linked with other translation variants.",
            },
        )

    existing_languages = {variant.language for variant in await _group_variants(db, group_id)}
    if source.language in existing_languages:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "language_already_exists",
                "message": f"This group already has a {source.language} variant.",
            },
        )

    has_progress = (
        await db.execute(
            select(func.count())
            .select_from(ModuleProgress)
            .where(ModuleProgress.translation_group_id == source.translation_group_id)
        )
    ).scalar_one()
    if has_progress:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "source_has_progress",
                "message": (
                    "This module already has learner progress recorded against it "
                    "and cannot be relinked."
                ),
            },
        )

    old_group_id = source.translation_group_id
    source.translation_group_id = group_id
    source.last_edited_by = author.id
    await db.flush()

    # The source's own auto-created group now holds nothing. It existed only to
    # satisfy "every module belongs to a group", which this module now does
    # under the one it just joined.
    old_group = await db.get(ModuleTranslationGroup, old_group_id)
    if old_group is not None:
        await db.delete(old_group)

    await record_audit_log(
        db,
        actor_user_id=author.id,
        action="translation_variant_linked",
        detail={
            "translation_group_id": str(group_id),
            "module_id": str(source.id),
            "language": source.language,
            "previous_translation_group_id": str(old_group_id),
        },
    )
    try:
        await db.commit()
    except IntegrityError as exc:
        # A concurrent link raced this one to the same language in the same
        # group — the unique constraint is the backstop the checks above
        # cannot fully close.
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "language_already_exists",
                "message": f"This group already has a {source.language} variant.",
            },
        ) from exc

    return await _translation_group_response(db, await _group_or_404(db, group_id))


@router.patch("/translation-groups/{group_id}", response_model=TranslationGroupResponse)
async def set_primary_variant(
    group_id: uuid.UUID,
    payload: SetPrimaryVariantRequest,
    db: AsyncSession = Depends(get_db),
    author: User = Depends(require_content_manager),
) -> TranslationGroupResponse:
    """Nominate which variant a learner whose language has none of the others gets."""
    group = await _group_or_404(db, group_id)
    module = await get_module_or_404(db, payload.primary_module_id)
    if module.translation_group_id != group_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="This module is not a variant of this translation group.",
        )

    group.primary_module_id = module.id

    await record_audit_log(
        db,
        actor_user_id=author.id,
        action="translation_primary_changed",
        detail={"translation_group_id": str(group_id), "primary_module_id": str(module.id)},
    )
    await db.commit()
    return await _translation_group_response(db, group)


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
