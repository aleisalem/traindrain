from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.config import get_settings
from app.dependencies import get_s3_client, get_ses_client
from app.routes.admin import router as admin_router
from app.routes.assets import delivery_router as asset_delivery_router
from app.routes.assets import router as content_assets_router
from app.routes.assignments import router as assignments_router
from app.routes.auth import router as auth_router
from app.routes.content import router as content_router
from app.routes.invites import router as invites_router
from app.routes.learning import catalog_router, me_router
from app.routes.profile import router as profile_router
from app.routes.reports import router as reports_router
from app.routes.transfer import router as transfer_router
from app.routes.two_factor import router as two_factor_router
from app.storage import ensure_assets_bucket


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    if settings.aws_endpoint_url:
        # LocalStack's SES emulation rejects sends from an unverified sender
        # identity. Real AWS SES verification happens out-of-band (domain +
        # DKIM setup), so this is a LocalStack-only dev convenience.
        get_ses_client().verify_email_identity(EmailAddress=settings.ses_sender_email)
        # Terraform owns the assets bucket in a real deployment (and the task
        # role cannot create one); this is what lets `docker-compose up` come
        # up ready to accept an upload with no bespoke setup step.
        await ensure_assets_bucket(get_s3_client())
    yield


app = FastAPI(title="TrainDrain API", lifespan=lifespan)
app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(content_router)
app.include_router(assignments_router)
app.include_router(content_assets_router)
app.include_router(asset_delivery_router)
app.include_router(catalog_router)
app.include_router(me_router)
app.include_router(invites_router)
app.include_router(profile_router)
app.include_router(reports_router)
app.include_router(transfer_router)
app.include_router(two_factor_router)


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "environment": get_settings().environment}
