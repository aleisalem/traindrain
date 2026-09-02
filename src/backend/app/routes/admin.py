from fastapi import APIRouter, Depends

from app.dependencies import require_administrator
from app.models import User

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/ping")
async def admin_ping(user: User = Depends(require_administrator)) -> dict[str, str]:
    return {"status": "ok"}
