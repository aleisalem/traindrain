from fastapi import FastAPI

from app.core.config import get_settings

app = FastAPI(title="TrainDrain API")


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "environment": get_settings().environment}
