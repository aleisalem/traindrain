import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
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
from app.dependencies import require_content_manager
from app.models import Module, ModulePage, ModuleTranslationGroup, User
from app.schemas.modules import (
    ModuleActor,
    ModuleCreateRequest,
    ModuleResponse,
    ModuleUpdateRequest,
    PageCreateRequest,
    PageDeleteRequest,
    PageReorderRequest,
    PageResponse,
    PagesResponse,
    PageUpdateRequest,
)
from app.security.audit import record_audit_log

router = APIRouter(prefix="/api/content", tags=["content"])

_MODULE_NOT_FOUND = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND, detail="Module not found."
)
_PAGE_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Page not found.")
_MAX_PAGES: int = CONSTRAINTS["limits"]["maxPagesPerModule"]


def _display_name(user: User) -> str:
    name = " ".join(part for part in (user.first_name, user.last_name) if part).strip()
    return name or user.email


async def _actors_by_id(db: AsyncSession, modules: list[Module]) -> dict[uuid.UUID, ModuleActor]:
    """Resolve every module's author and last editor in one query, not per row."""
    user_ids = {module.created_by for module in modules} | {
        module.last_edited_by for module in modules
    }
    if not user_ids:
        return {}
    users = (await db.execute(select(User).where(User.id.in_(user_ids)))).scalars()
    return {user.id: ModuleActor(id=user.id, display_name=_display_name(user)) for user in users}


def _to_module_response(module: Module, actors: dict[uuid.UUID, ModuleActor]) -> ModuleResponse:
    return ModuleResponse(
        id=module.id,
        translation_group_id=module.translation_group_id,
        language=module.language,
        title=module.title,
        description=module.description,
        estimated_duration_minutes=module.estimated_duration_minutes,
        status=module.status,
        created_by=actors[module.created_by],
        last_edited_by=actors[module.last_edited_by],
        created_at=module.created_at,
        updated_at=module.updated_at,
    )


async def _get_module(db: AsyncSession, module_id: uuid.UUID) -> Module:
    module = (
        await db.execute(select(Module).where(Module.id == module_id))
    ).scalar_one_or_none()
    if module is None:
        raise _MODULE_NOT_FOUND
    return module


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
    actors = await _actors_by_id(db, modules)
    return [_to_module_response(module, actors) for module in modules]


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

    actors = await _actors_by_id(db, [module])
    return _to_module_response(module, actors)


@router.get("/modules/{module_id}", response_model=ModuleResponse)
async def get_module(
    module_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    author: User = Depends(require_content_manager),
) -> ModuleResponse:
    module = await _get_module(db, module_id)
    actors = await _actors_by_id(db, [module])
    return _to_module_response(module, actors)


@router.patch("/modules/{module_id}", response_model=ModuleResponse)
async def update_module(
    module_id: uuid.UUID,
    payload: ModuleUpdateRequest,
    db: AsyncSession = Depends(get_db),
    author: User = Depends(require_content_manager),
) -> ModuleResponse:
    module = await _get_module(db, module_id)

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

    actors = await _actors_by_id(db, [module])
    return _to_module_response(module, actors)


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
    module = await _get_module(db, module_id)
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
    module = await _get_module(db, module_id)
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
    module = await _get_module(db, module_id)
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
    module = await _get_module(db, module_id)
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
    module = await _get_module(db, module_id)
    page = await _get_page(db, module.id, page_id)

    _claim_draft(module, payload.draft_revision, author)

    await db.delete(page)
    await db.flush()

    # Positions stay contiguous from 0, so "page 3 of 7" never has a gap.
    for position, remaining in enumerate(await _module_pages(db, module.id)):
        remaining.position = position

    await db.commit()
    return await _pages_response(db, module)
