from fastapi import FastAPI

from app.core.config import get_settings
from app.routes.admin import router as admin_router
from app.routes.auth import router as auth_router

app = FastAPI(title="TrainDrain API")
app.include_router(auth_router)
app.include_router(admin_router)


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "environment": get_settings().environment}
