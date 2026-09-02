from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings, sourced from environment variables / .env.

    Never hardcode secrets here — every field is either a non-secret default
    or must be supplied at runtime via the environment.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "development"
    database_url: str
    bootstrap_admin_email: str = "admin@traindrain.local"

    # Invite emails (and, later, password-reset emails) are sent via SES —
    # AWS SES in production (region only, no endpoint override, credentials
    # from the ECS task role), LocalStack's SES emulation locally.
    aws_region: str = "eu-central-1"
    aws_endpoint_url: str | None = None
    ses_sender_email: str = "no-reply@traindrain.local"
    # Base URL the frontend is served from — used to build the invite-accept link.
    frontend_base_url: str = "http://localhost:8080"


@lru_cache
def get_settings() -> Settings:
    return Settings()
