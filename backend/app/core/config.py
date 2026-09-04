"""Application settings, loaded from environment variables."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    # General
    project_name: str = "susoDash"
    environment: str = "production"
    public_url: str = "http://localhost:8080"
    # The domain shared dashboards are named under, e.g. "dash.example.org",
    # so a dashboard can answer on labour-force.dash.example.org. Empty turns
    # the feature off, because without a wildcard DNS record and a wildcard
    # certificate for it, a name would resolve to nothing.
    dashboard_domain: str = ""
    log_level: str = "INFO"
    api_v1_prefix: str = "/api/v1"

    # Security
    secret_key: str = "insecure-development-key-change-me"
    encryption_key: str = ""
    access_token_expire_minutes: int = 60 * 24
    algorithm: str = "HS256"
    # Comma separated, e.g. "https://a.example,https://b.example". Held as a
    # plain string on purpose: pydantic-settings JSON-decodes environment values
    # for list-typed fields before any validator runs, so a bare
    # "http://host:8080" raises SettingsError and the process dies at start-up.
    # Read it through cors_origin_list, never directly.
    cors_origins: str = "http://localhost:5173"

    # Bootstrap admin
    first_admin_email: str = "admin@example.com"
    first_admin_password: str = "changeme"
    first_admin_name: str = "Administrator"

    # Database
    postgres_user: str = "surveyhq"
    postgres_password: str = "surveyhq"
    postgres_db: str = "surveyhq"
    postgres_host: str = "postgres"
    postgres_port: int = 5432
    database_url_override: str = ""

    # Redis / Celery
    redis_url: str = "redis://redis:6379/0"

    # Storage
    storage_dir: str = "/data"
    max_upload_mb: int = 512

    # Mail
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_tls: bool = True
    smtp_from: str = "susoDash <no-reply@example.com>"

    # Scheduler
    sync_tick_minutes: int = 5
    monitor_tick_minutes: int = 15

    @property
    def cors_origin_list(self) -> list[str]:
        raw = self.cors_origins.strip()
        # A JSON array is also accepted: it was the workaround while the plain
        # comma separated form crashed, so deployments still carry it.
        if raw.startswith("["):
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                return []
            return [str(item).strip() for item in parsed if str(item).strip()]
        return [item.strip() for item in raw.split(",") if item.strip()]

    @property
    def database_url(self) -> str:
        if self.database_url_override:
            return self.database_url_override
        return (
            f"postgresql+psycopg2://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def storage_path(self) -> Path:
        return Path(self.storage_dir)

    @property
    def datasets_path(self) -> Path:
        return self.storage_path / "datasets"

    @property
    def uploads_path(self) -> Path:
        return self.storage_path / "uploads"

    @property
    def exports_path(self) -> Path:
        return self.storage_path / "exports"

    def ensure_directories(self) -> None:
        for path in (self.datasets_path, self.uploads_path, self.exports_path):
            path.mkdir(parents=True, exist_ok=True)

    @property
    def mail_enabled(self) -> bool:
        return bool(self.smtp_host)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
