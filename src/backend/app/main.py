from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.config import get_settings
from app.dependencies import get_ses_client
from app.routes.admin import router as admin_router
from app.routes.auth import router as auth_router
from app.routes.invites import router as invites_router
from app.routes.profile import router as profile_router
from app.routes.two_factor import router as two_factor_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    if settings.aws_endpoint_url:
        # LocalStack's SES emulation rejects sends from an unverified sender
        # identity. Real AWS SES verification happens out-of-band (domain +
        # DKIM setup), so this is a LocalStack-only dev convenience.
        get_ses_client().verify_email_identity(EmailAddress=settings.ses_sender_email)
    yield


app = FastAPI(title="TrainDrain API", lifespan=lifespan)
app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(invites_router)
app.include_router(profile_router)
app.include_router(two_factor_router)


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "environment": get_settings().environment}
