from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central application configuration, sourced from environment variables.

    No secret ever has a default value here — a missing required setting
    should fail loudly at startup, not silently fall back to something that
    works on one machine and not another.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "TerraRisk Credit Intelligence API"
    app_version: str = "0.1.0"
    environment: str = "development"
    # Secure by default: verbose SQL logging (app/database/base.py echoes
    # every statement + bound parameter value when this is True) must be an
    # explicit opt-in via .env, never a silent default a deployer forgot to
    # turn off — bound parameters can carry PII (farmer_identity fields)
    # once populated.
    debug: bool = False

    database_url: str

    jwt_secret: str
    jwt_algorithm: str = "HS256"
    jwt_expires_minutes: int = 60 * 12

    gee_project_id: str | None = None
    gee_service_account_json_path: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
