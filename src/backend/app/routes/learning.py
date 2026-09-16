"""The learner's side of the platform: the catalog, the viewer, and progress.

Two routers, because these are two questions:

* `catalog_router` (`/api/catalog/...`) — what is on offer to everyone.
* `me_router` (`/api/me/...`) — what *this* learner has open, has read, and has
  attested to.

Everything here is addressed by `translation_group_id` rather than module id.
A learner is reading a body of material, not one particular text of it: which
language variant they get is resolved on open, so a group that gains a German
translation next month needs no link anywhere to change.

Learners read a **version snapshot**, never `module_pages`. The draft is the
author's workspace and may be half-written at any moment; what a learner sees is
what an author deliberately froze, which is also what makes a completion record
able to name exactly what was read.
"""

import uuid
from datetime import UTC, date, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.access import may_read_module
from app.assignments import (
    AssignedModule,
    assigned_translation_group_ids,
    assignments_for_user,
    is_overdue,
)
from app.db import get_db
from app.dependencies import require_active_user
from app.models import (
    Module,
    ModuleAsset,
    ModuleProgress,
    ModuleTranslationGroup,
    ModuleVersion,
    User,
)
from app.routes.assets import asset_url
from app.schemas.learning import (
    CatalogEntry,
    LearnerAttachment,
    LearnerModule,
    LearnerModuleSummary,
    LearnerPage,
    ProgressState,
    SwitchLanguageRequest,
)
from app.security.system_settings import deployment_today

catalog_router = APIRouter(prefix="/api/catalog", tags=["learning"])
me_router = APIRouter(prefix="/api/me", tags=["learning"])

# One answer for "there is nothing here for you", whether the material never
# existed, was never opened to this learner, or has since been taken out of
# circulation. Deliberately indistinguishable: which of those it is would tell
# somebody who may not read a module that it is nonetheless there.
_UNAVAILABLE = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND,
    detail={
        "code": "module_unavailable",
        "message": "This module is no longer available.",
    },
)


async def _published_variants(db: AsyncSession, group_ids: list[uuid.UUID]) -> list[Module]:
    """Every variant of these groups that a learner could be shown."""
    if not group_ids:
        return []
    return list(
        (
            await db.execute(
                select(Module).where(
                    Module.translation_group_id.in_(group_ids),
                    Module.status == "published",
                    Module.current_version_id.is_not(None),
                )
            )
        ).scalars()
    )


def _pick_variant(
    variants: list[Module],
    *,
    preferred_language: str | None,
    primary_module_id: uuid.UUID | None,
    sticky_module_id: uuid.UUID | None = None,
) -> Module | None:
    """Which text of this material does this learner get?

    In priority order: the variant they are already reading, so a profile
    language change (or simply asking twice) never pulls them onto a different
    text mid-module than the one their `pages_viewed` was collected against —
    an explicit switch (`switch_variant_language` below) is the only thing
    allowed to move that. Absent that, their own language; absent that, the
    group's primary, so somebody whose language has no translation still gets
    the material rather than nothing; absent that, any published variant,
    picked deterministically so two requests agree.
    """
    if not variants:
        return None
    ordered = sorted(variants, key=lambda module: (module.language, str(module.id)))
    if sticky_module_id is not None:
        for variant in ordered:
            if variant.id == sticky_module_id:
                return variant
    for variant in ordered:
        if preferred_language and variant.language == preferred_language:
            return variant
    for variant in ordered:
        if variant.id == primary_module_id:
            return variant
    return ordered[0]


async def _resolve_readable_variant(
    db: AsyncSession,
    user: User,
    group_id: uuid.UUID,
    assigned_group_ids: frozenset[uuid.UUID],
) -> tuple[Module, ModuleVersion]:
    """The module this learner opens, and the frozen text they read of it.

    Raises the one 404 above if there is nothing they may read — an unknown
    group, a group with no published variant, and a module the author never
    opened to anybody (by catalog or by assignment) are the same answer on
    purpose.
    """
    group = await db.get(ModuleTranslationGroup, group_id)
    candidates = await _published_variants(db, [group_id]) if group else []
    readable = [
        module
        for module in candidates
        if may_read_module(user, module, assigned_group_ids=assigned_group_ids)
    ]
    existing = await _existing_progress(db, user, group_id)
    variant = _pick_variant(
        readable,
        preferred_language=user.preferred_language,
        primary_module_id=group.primary_module_id if group else None,
        sticky_module_id=existing.module_id if existing else None,
    )
    if variant is None or variant.current_version_id is None:
        raise _UNAVAILABLE

    version = await db.get(ModuleVersion, variant.current_version_id)
    if version is None:
        raise _UNAVAILABLE
    return variant, version


def _snapshot_pages(version: ModuleVersion) -> list[dict[str, Any]]:
    pages: list[dict[str, Any]] = version.snapshot.get("pages", [])
    return sorted(pages, key=lambda page: page["position"])


def _to_progress_state(progress: ModuleProgress) -> ProgressState:
    return ProgressState(
        pages_viewed=[uuid.UUID(page_id) for page_id in progress.pages_viewed],
        current_page_id=progress.current_page_id,
        started_at=progress.started_at,
        completed_at=progress.completed_at,
        completed_version_number=progress.completed_version_number,
        completed_module_id=progress.completed_module_id,
        superseded_at=progress.superseded_at,
    )


async def _versions_by_id(
    db: AsyncSession, modules: list[Module]
) -> dict[uuid.UUID, ModuleVersion]:
    """The published text of each of these modules, in one query.

    Every list a learner sees names the material by its *published* title, the
    same one the viewer shows — a rename made to the draft since then belongs to
    the author's work in progress, not to what anybody is reading.
    """
    version_ids = [module.current_version_id for module in modules if module.current_version_id]
    if not version_ids:
        return {}
    rows = (
        await db.execute(select(ModuleVersion).where(ModuleVersion.id.in_(version_ids)))
    ).scalars()
    return {version.id: version for version in rows}


async def _progress_rows(
    db: AsyncSession, user: User, group_ids: list[uuid.UUID]
) -> dict[uuid.UUID, ModuleProgress]:
    if not group_ids:
        return {}
    rows = (
        await db.execute(
            select(ModuleProgress).where(
                ModuleProgress.user_id == user.id,
                ModuleProgress.translation_group_id.in_(group_ids),
            )
        )
    ).scalars()
    return {row.translation_group_id: row for row in rows}


async def _existing_progress(
    db: AsyncSession, user: User, group_id: uuid.UUID
) -> ModuleProgress | None:
    """This learner's progress row, if they have one. Reads only."""
    return (
        await db.execute(
            select(ModuleProgress).where(
                ModuleProgress.user_id == user.id,
                ModuleProgress.translation_group_id == group_id,
            )
        )
    ).scalar_one_or_none()


async def _claim_progress(db: AsyncSession, user: User, module: Module) -> ModuleProgress:
    """This learner's progress row for this material, created if it is their first read.

    Inserted with `ON CONFLICT DO NOTHING` and then read back under a row lock,
    so two tabs opening the same module at once produce one row and one of them
    waits rather than both reading an array, both appending to it, and one of
    the two pages quietly un-viewing itself.
    """
    await db.execute(
        pg_insert(ModuleProgress)
        .values(
            id=uuid.uuid4(),
            user_id=user.id,
            translation_group_id=module.translation_group_id,
            module_id=module.id,
            pages_viewed=[],
        )
        .on_conflict_do_nothing(constraint="uq_module_progress_learner")
    )
    return (
        await db.execute(
            select(ModuleProgress)
            .where(
                ModuleProgress.user_id == user.id,
                ModuleProgress.translation_group_id == module.translation_group_id,
            )
            .with_for_update()
        )
    ).scalar_one()


# --- The open catalog -----------------------------------------------------


@catalog_router.get("/modules", response_model=list[CatalogEntry])
async def list_catalog(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_active_user),
) -> list[CatalogEntry]:
    """What any learner may read of their own accord.

    Only modules an author both published *and* opted into the catalog. The
    default is false, so silence means no: material reaches nobody until
    somebody says it should.
    """
    modules = list(
        (
            await db.execute(
                select(Module)
                .where(
                    Module.catalog_visible.is_(True),
                    Module.status == "published",
                    Module.current_version_id.is_not(None),
                )
                .order_by(Module.title)
            )
        ).scalars()
    )

    by_group: dict[uuid.UUID, list[Module]] = {}
    for module in modules:
        by_group.setdefault(module.translation_group_id, []).append(module)
    if not by_group:
        return []

    groups = (
        await db.execute(
            select(ModuleTranslationGroup).where(
                ModuleTranslationGroup.id.in_(list(by_group))
            )
        )
    ).scalars()
    primaries = {group.id: group.primary_module_id for group in groups}
    progress = await _progress_rows(db, user, list(by_group))

    # One entry per body of material rather than one per text of it: two
    # language variants of the same module are one thing to read, not two. A
    # learner already reading or having completed one variant sees that same
    # one here too — the card and the viewer must never disagree about which
    # text "completed" refers to.
    chosen = [
        variant
        for group_id, variants in by_group.items()
        if (
            variant := _pick_variant(
                variants,
                preferred_language=user.preferred_language,
                primary_module_id=primaries.get(group_id),
                sticky_module_id=(
                    progress[group_id].module_id if group_id in progress else None
                ),
            )
        )
        is not None
    ]

    # Every module here was selected with a non-null `current_version_id`, and
    # the column is a foreign key, so each one resolves.
    versions = await _versions_by_id(db, chosen)

    entries = []
    for module in chosen:
        snapshot = versions[module.current_version_id].snapshot
        row = progress.get(module.translation_group_id)
        entries.append(
            CatalogEntry(
                translation_group_id=module.translation_group_id,
                language=module.language,
                # The published title, not the draft's: the card and the module
                # a learner then opens have to say the same thing.
                title=snapshot.get("title", module.title),
                description=snapshot.get("description"),
                estimated_duration_minutes=snapshot.get("estimated_duration_minutes"),
                page_count=len(snapshot.get("pages", [])),
                started=row is not None,
                completed_at=row.completed_at if row else None,
                superseded_at=row.superseded_at if row else None,
            )
        )
    return sorted(entries, key=lambda entry: entry.title.lower())


# --- The learner's own material -------------------------------------------


async def _unstarted_assigned_summaries(
    db: AsyncSession,
    user: User,
    group_ids: list[uuid.UUID],
    assignments: dict[uuid.UUID, AssignedModule],
    assigned_group_ids: frozenset[uuid.UUID],
    today: date,
) -> list[LearnerModuleSummary]:
    """Rows for material assigned to this learner that they have not opened.

    Nothing is written here — this is a read composing the same resolution the
    viewer uses (`_pick_variant`) over material the learner has no progress
    row for yet, so the list can say "you have this to do" before they have
    clicked into it once.
    """
    if not group_ids:
        return []

    candidates = await _published_variants(db, group_ids)
    readable = [
        module
        for module in candidates
        if may_read_module(user, module, assigned_group_ids=assigned_group_ids)
    ]
    by_group: dict[uuid.UUID, list[Module]] = {}
    for module in readable:
        by_group.setdefault(module.translation_group_id, []).append(module)
    if not by_group:
        return []

    groups = {
        group.id: group
        for group in (
            await db.execute(
                select(ModuleTranslationGroup).where(
                    ModuleTranslationGroup.id.in_(list(by_group))
                )
            )
        ).scalars()
    }
    chosen = {
        group_id: variant
        for group_id, variants in by_group.items()
        if (
            variant := _pick_variant(
                variants,
                preferred_language=user.preferred_language,
                primary_module_id=(
                    groups[group_id].primary_module_id if group_id in groups else None
                ),
            )
        )
        is not None
    }
    versions = await _versions_by_id(db, list(chosen.values()))

    summaries = []
    for group_id, variant in chosen.items():
        version = versions.get(variant.current_version_id) if variant.current_version_id else None
        if version is None:
            # Assigned material with nothing published yet has nothing to show.
            continue
        assignment = assignments[group_id]
        snapshot = version.snapshot
        summaries.append(
            LearnerModuleSummary(
                translation_group_id=group_id,
                title=snapshot.get("title", variant.title),
                language=variant.language,
                estimated_duration_minutes=snapshot.get(
                    "estimated_duration_minutes", variant.estimated_duration_minutes
                ),
                started_at=None,
                completed_at=None,
                completed_version_number=None,
                superseded_at=None,
                available=True,
                due_date=assignment.due_date,
                requirement=assignment.requirement,
                overdue=is_overdue(assignment.due_date, completed=False, today=today),
            )
        )
    return summaries


@me_router.get("/modules", response_model=list[LearnerModuleSummary])
async def list_my_modules(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_active_user),
) -> list[LearnerModuleSummary]:
    """What this learner has started, what they have completed, and what they
    have been assigned but not opened yet — the union the PRD calls their
    assigned list, with the nearest due date and an overdue flag on each row.
    """
    rows = list(
        (
            await db.execute(
                select(ModuleProgress)
                .where(ModuleProgress.user_id == user.id)
                .order_by(ModuleProgress.started_at.desc())
            )
        ).scalars()
    )

    assignments = await assignments_for_user(db, user)
    assigned_group_ids = frozenset(assignments)
    today = await deployment_today(db)

    if not rows and not assignments:
        return []

    started_group_ids = {row.translation_group_id for row in rows}
    group_ids = sorted(started_group_ids | assigned_group_ids)

    def _display_module_id(row: ModuleProgress) -> uuid.UUID:
        # The variant a completion names, once there is one — not whichever
        # variant is currently being read, which an explicit language switch
        # (ticket 6) can move on to a different variant with its own version
        # numbering. Showing that one instead would pair `completed_version_number`
        # with the wrong module's title and language.
        return row.completed_module_id or row.module_id

    # The variant they actually read, not whichever one they would resolve to
    # today. `module_progress.module_id`/`completed_module_id` are foreign keys
    # and a deleted module leaves a tombstone row behind, so every one of these
    # resolves.
    read_modules = {
        module.id: module
        for module in (
            await db.execute(
                select(Module).where(Module.id.in_([_display_module_id(row) for row in rows]))
            )
        ).scalars()
    } if rows else {}
    published = await _versions_by_id(db, list(read_modules.values()))
    available_groups = {
        module.translation_group_id
        for module in await _published_variants(db, group_ids)
        if may_read_module(user, module, assigned_group_ids=assigned_group_ids)
    }

    summaries = []
    for row in rows:
        module = read_modules[_display_module_id(row)]
        version = published.get(module.current_version_id) if module.current_version_id else None
        snapshot = version.snapshot if version else {}
        assignment = assignments.get(row.translation_group_id)
        completed = row.completed_at is not None and row.superseded_at is None
        summaries.append(
            LearnerModuleSummary(
                translation_group_id=row.translation_group_id,
                # The published title, so this list and the viewer agree.
                title=snapshot.get("title", module.title),
                language=module.language,
                estimated_duration_minutes=snapshot.get(
                    "estimated_duration_minutes", module.estimated_duration_minutes
                ),
                started_at=row.started_at,
                completed_at=row.completed_at,
                completed_version_number=row.completed_version_number,
                superseded_at=row.superseded_at,
                available=row.translation_group_id in available_groups,
                due_date=assignment.due_date if assignment else None,
                requirement=assignment.requirement if assignment else None,
                overdue=(
                    is_overdue(assignment.due_date, completed=completed, today=today)
                    if assignment
                    else False
                ),
            )
        )

    unstarted_group_ids = sorted(assigned_group_ids - started_group_ids)
    summaries.extend(
        await _unstarted_assigned_summaries(
            db, user, unstarted_group_ids, assignments, assigned_group_ids, today
        )
    )
    return summaries


async def _readable_variants(
    db: AsyncSession,
    user: User,
    group_id: uuid.UUID,
    assigned_group_ids: frozenset[uuid.UUID],
) -> list[Module]:
    return [
        module
        for module in await _published_variants(db, [group_id])
        if may_read_module(user, module, assigned_group_ids=assigned_group_ids)
    ]


async def _to_learner_module(
    db: AsyncSession,
    module: Module,
    version: ModuleVersion,
    progress: ModuleProgress | None,
    available_languages: list[str],
) -> LearnerModule:
    attachments = (
        await db.execute(
            select(ModuleAsset)
            .where(ModuleAsset.module_id == module.id, ModuleAsset.kind == "attachment")
            .order_by(ModuleAsset.created_at)
        )
    ).scalars()

    snapshot = version.snapshot
    return LearnerModule(
        translation_group_id=module.translation_group_id,
        module_id=module.id,
        language=snapshot.get("language", module.language),
        # From the snapshot, not the row: the title a learner reads has to be
        # the one that was published with the text, not a rename made since.
        title=snapshot.get("title", module.title),
        description=snapshot.get("description"),
        estimated_duration_minutes=snapshot.get("estimated_duration_minutes"),
        version_number=version.version_number,
        pages=[
            LearnerPage(
                id=uuid.UUID(page["id"]),
                position=page["position"],
                title=page["title"],
                schema_version=page["schema_version"],
                body=page["body"],
            )
            for page in _snapshot_pages(version)
        ],
        attachments=[
            LearnerAttachment(
                id=asset.id,
                url=asset_url(module.id, asset.id),
                original_filename=asset.original_filename,
                content_type=asset.content_type,
                size_bytes=asset.size_bytes,
            )
            for asset in attachments
        ],
        progress=None if progress is None else _to_progress_state(progress),
        # Every language this learner could switch to, so the viewer can offer
        # the choice only when there is one to make.
        available_languages=available_languages,
    )


@me_router.get("/modules/{translation_group_id}", response_model=LearnerModule)
async def get_my_module(
    translation_group_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_active_user),
) -> LearnerModule:
    """Open a module: its frozen pages, its attachments, and where you were.

    A read, and only a read: the progress record starts when the learner first
    reads a *page*, which the viewer reports one page at a time. Making a GET
    write would also make it something a prefetch or a stray click could record
    on somebody's training history.
    """
    assigned = await assigned_translation_group_ids(db, user)
    module, version = await _resolve_readable_variant(db, user, translation_group_id, assigned)
    progress = await _existing_progress(db, user, module.translation_group_id)
    readable = await _readable_variants(db, user, translation_group_id, assigned)

    return await _to_learner_module(
        db, module, version, progress, sorted({variant.language for variant in readable})
    )


@me_router.post("/modules/{translation_group_id}/language", response_model=LearnerModule)
async def switch_variant_language(
    translation_group_id: uuid.UUID,
    payload: SwitchLanguageRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_active_user),
) -> LearnerModule:
    """An explicit choice of which text to read, overriding automatic resolution.

    Unlike opening a module, this writes: `pages_viewed` is reset to match the
    newly-chosen text, because a page id only means the same page within the
    variant it belongs to. `started_at`, `completed_at`, and
    `completed_version_number` are left alone — switching text is not starting
    over, and a prior completion still happened on the date it happened.
    """
    assigned = await assigned_translation_group_ids(db, user)
    readable = await _readable_variants(db, user, translation_group_id, assigned)
    target = next((module for module in readable if module.language == payload.language), None)
    if target is None or target.current_version_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "variant_unavailable",
                "message": "No published text in that language is available.",
            },
        )
    version = await db.get(ModuleVersion, target.current_version_id)
    if version is None:
        raise _UNAVAILABLE

    progress = await _claim_progress(db, user, target)
    if progress.module_id != target.id:
        progress.module_id = target.id
        progress.pages_viewed = []
        progress.current_page_id = None
    await db.commit()

    return await _to_learner_module(
        db, target, version, progress, sorted({variant.language for variant in readable})
    )


@me_router.post(
    "/modules/{translation_group_id}/pages/{page_id}/view", response_model=ProgressState
)
async def record_page_view(
    translation_group_id: uuid.UUID,
    page_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_active_user),
) -> ProgressState:
    """Record that this page was read, and that it is where the learner is now.

    The page has to belong to the version being read — an id from somewhere
    else is a 404 rather than a silently-accepted entry in the array, since
    that array is what the attestation is checked against.
    """
    assigned = await assigned_translation_group_ids(db, user)
    module, version = await _resolve_readable_variant(db, user, translation_group_id, assigned)
    page_ids = {page["id"] for page in _snapshot_pages(version)}
    if str(page_id) not in page_ids:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Page not found.")

    progress = await _claim_progress(db, user, module)
    if str(page_id) not in progress.pages_viewed:
        # Reassigned rather than appended: a mutated-in-place JSONB list is not
        # seen as dirty by SQLAlchemy and would never be written back.
        progress.pages_viewed = [*progress.pages_viewed, str(page_id)]
    progress.current_page_id = page_id
    await db.commit()
    return _to_progress_state(progress)


@me_router.post("/modules/{translation_group_id}/complete", response_model=ProgressState)
async def complete_module(
    translation_group_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_active_user),
) -> ProgressState:
    """The attestation: "I have read and understood this."

    Refused until every page of the version being read has been viewed. This is
    the one thing in the release a learner asserts about themselves, and an
    assertion that can be made without having seen the material would be worth
    nothing to the person who later has to rely on it.

    Re-attesting after a revision is allowed and updates the record — that is
    exactly what a substantive republish asks a learner to do, and by then the
    publish has emptied their `pages_viewed`, so the check above is a real gate
    on the new text rather than a formality satisfied by the old one.
    """
    assigned = await assigned_translation_group_ids(db, user)
    module, version = await _resolve_readable_variant(db, user, translation_group_id, assigned)
    progress = await _claim_progress(db, user, module)

    page_ids = [page["id"] for page in _snapshot_pages(version)]
    outstanding = [page_id for page_id in page_ids if page_id not in set(progress.pages_viewed)]
    if outstanding:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "pages_outstanding",
                "message": "Read every page of this module before confirming.",
                "pages_outstanding": len(outstanding),
                "pages_total": len(page_ids),
            },
        )

    progress.completed_at = datetime.now(UTC)
    progress.completed_version_number = version.version_number
    progress.completed_module_id = module.id
    # A completion of the current text is current by definition, whatever a
    # previous substantive republish had marked.
    progress.superseded_at = None
    await db.commit()
    return _to_progress_state(progress)
