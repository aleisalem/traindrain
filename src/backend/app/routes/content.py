import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.dependencies import require_content_manager
from app.models import Module, ModuleTranslationGroup, User
from app.schemas.modules import (
    ModuleActor,
    ModuleCreateRequest,
    ModuleResponse,
    ModuleUpdateRequest,
)
from app.security.audit import record_audit_log

router = APIRouter(prefix="/api/content", tags=["content"])

_MODULE_NOT_FOUND = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND, detail="Module not found."
)


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
