from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# The literal placeholder value shipped in backend/.env.example and
# .env.example — never a real secret, but a plausible one someone could
# forget to replace. Checked by value, not just length, since a copy-pasted
# placeholder can happen to be long enough to pass a length check alone.
_EXAMPLE_JWT_SECRET = "replace-with-a-generated-secret"
_MIN_PRODUCTION_JWT_SECRET_LENGTH = 32


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

    # Water Intelligence (docs/Water_Intelligence_Service_Blueprint.md, D9)
    # — a SEPARATE service-account credential from gee_project_id /
    # gee_service_account_json_path above, even when both point at the same
    # GCP project, so a Water Intelligence usage spike cannot degrade
    # Service 1's GEE quota/SLA. No fallback to the Service 1 credential:
    # this class's own docstring says a missing required setting should
    # fail loudly, not silently reuse a value that would defeat the whole
    # point of the isolation.
    gee_hydrology_project_id: str | None = None
    gee_hydrology_service_account_json_path: str | None = None

    # M2A (Blueprint §10 M2) — the Next.js frontend's origin, and only that
    # origin: no wildcard, since requests carry a bearer token. Defaults to
    # the local Next.js dev server so `npm run dev` works out of the box;
    # override per-environment via .env, never hardcode a second origin in.
    frontend_origin: str = "http://localhost:3000"

    # M2A P6 — where rendered report PDFs are cached (Blueprint §API:
    # "cached after first render"). Relative paths resolve against the
    # backend working directory; deployments should point this at a
    # persistent volume.
    report_pdf_cache_dir: str = "var/pdf_cache"

    @model_validator(mode="after")
    def _validate_production_safety(self) -> "Settings":
        """M3 — quick production-configuration checks, not an auth redesign.

        A weak/placeholder JWT_SECRET or DEBUG=True currently starts up
        without complaint in any environment, including production — this
        closes that gap the same fail-loudly way this class already treats
        every other required setting (see the class docstring). Local/dev/
        test environments are untouched; `ENVIRONMENT=production` is the
        explicit opt-in these checks gate on.
        """
        if self.environment != "production":
            return self

        if self.jwt_secret == _EXAMPLE_JWT_SECRET or len(self.jwt_secret) < _MIN_PRODUCTION_JWT_SECRET_LENGTH:
            raise ValueError(
                "JWT_SECRET is missing, is the example placeholder, or is under "
                f"{_MIN_PRODUCTION_JWT_SECRET_LENGTH} characters — refusing to start with "
                "ENVIRONMENT=production. Generate a real secret: "
                'python -c "import secrets; print(secrets.token_urlsafe(32))"'
            )
        if self.debug:
            raise ValueError(
                "DEBUG=True with ENVIRONMENT=production — verbose SQL logging can log PII-bearing "
                "bound parameters (see this file's own debug field comment). Refusing to start."
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
