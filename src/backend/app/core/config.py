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


@lru_cache
def get_settings() -> Settings:
    return Settings()
