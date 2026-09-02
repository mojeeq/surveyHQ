"""Application settings, loaded from environment variables."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    # General
    project_name: str = "SurveyHQ"
    environment: str = "production"
    public_url: str = "http://localhost:8080"
    log_level: str = "INFO"
    api_v1_prefix: str = "/api/v1"

    # Security
    secret_key: str = "insecure-development-key-change-me"
    encryption_key: str = ""
    access_token_expire_minutes: int = 60 * 24
    algorithm: str = "HS256"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

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
    smtp_from: str = "SurveyHQ <no-reply@example.com>"

    # Scheduler
    sync_tick_minutes: int = 5
    monitor_tick_minutes: int = 15

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

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
