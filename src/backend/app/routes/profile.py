from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.dependencies import require_active_user
from app.models import User
from app.schemas.profile import ProfileResponse, UpdateNameRequest, UpdatePreferencesRequest

router = APIRouter(prefix="/api/profile", tags=["profile"])


def _to_response(user: User) -> ProfileResponse:
    return ProfileResponse(
        id=str(user.id),
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        preferred_language=user.preferred_language,
        preferred_theme=user.preferred_theme,
    )


@router.patch("/name", response_model=ProfileResponse)
async def update_name(
    payload: UpdateNameRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_active_user),
) -> ProfileResponse:
    user.first_name = payload.first_name
    user.last_name = payload.last_name
    await db.commit()
    return _to_response(user)


@router.patch("/preferences", response_model=ProfileResponse)
async def update_preferences(
    payload: UpdatePreferencesRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_active_user),
) -> ProfileResponse:
    user.preferred_language = payload.preferred_language
    user.preferred_theme = payload.preferred_theme
    await db.commit()
    return _to_response(user)
