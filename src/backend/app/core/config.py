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

    # --- Module assets ----------------------------------------------------
    #
    # A private bucket: public access blocked, server-side encryption on.
    # Terraform provisions it in a real deployment; locally the backend creates
    # it in LocalStack on startup so `docker-compose up` needs no setup step.
    assets_bucket: str = "traindrain-assets"
    # Presigned URLs are handed to a browser, so they have to be signed against
    # an endpoint the *browser* can reach. Inside docker-compose the API talks
    # to LocalStack as `http://localstack:4566`, which means nothing on the
    # host — hence a separate, browser-facing endpoint for signing. Unset in
    # production, where a presigned URL points at the bucket's own S3 origin.
    s3_public_endpoint_url: str | None = None
    # Short-lived by design: long enough for a page of images to load, short
    # enough that a URL copied out of a network log is useless before long.
    asset_url_ttl_seconds: int = 300
    asset_max_image_bytes: int = 5 * 1024 * 1024
    asset_max_attachment_bytes: int = 20 * 1024 * 1024
    asset_max_module_bytes: int = 100 * 1024 * 1024

    # --- Module export/import (ticket 12) ---------------------------------
    #
    # A `.zip` is hostile input twice over: an attacker-sized upload, and an
    # attacker-crafted archive that decompresses to far more than it claims.
    # `import_max_archive_bytes` bounds the upload itself (the compressed
    # bytes read from the request); the rest bound what parsing the archive
    # is allowed to do to memory, independent of what the archive's own
    # metadata claims about itself.
    import_max_archive_bytes: int = 50 * 1024 * 1024
    import_max_entries: int = 200
    import_max_compression_ratio: int = 100
    import_max_uncompressed_bytes: int = 150 * 1024 * 1024

    # Envelope-encryption key for TOTP secrets at rest (base64-encoded 32
    # bytes, AES-256-GCM) — AWS Secrets Manager in production (injected into
    # this env var by the ECS task definition), a local-only value in dev.
    # No default: this is a real secret, never hardcoded per project policy.
    two_factor_encryption_key: str


@lru_cache
def get_settings() -> Settings:
    return Settings()
