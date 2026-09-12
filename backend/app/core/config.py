"""Application settings, loaded from environment variables."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_SECRET_KEYS = {"insecure-development-key-change-me"}
DEFAULT_FIRST_ADMIN_EMAILS = {"admin@example.com"}
DEFAULT_FIRST_ADMIN_PASSWORDS = {"changeme", "CHANGE-ME-strong-password"}
NON_PRODUCTION_ENVIRONMENTS = {"development", "dev", "test", "testing", "local"}


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

    # Analytics / DuckDB. Zero threads means choose a conservative value from
    # the machine's CPU count. Keeping these deployment settings rather than
    # literals in query_engine lets an 8-core VM and a 32-core analytical host
    # use very different resource envelopes without rebuilding the image.
    duckdb_threads: int = 0
    duckdb_memory_limit: str = "2GB"
    duckdb_temp_dir: str = ""
    analytics_cache_enabled: bool = True
    analytics_cache_ttl_seconds: int = 300
    # Large delimited Survey Solutions members bypass pandas and are parsed by
    # DuckDB directly once they cross this on-disk threshold.
    duckdb_csv_above_mb: int = 32
    monitoring_precompute_enabled: bool = True

    # Rate limiting. On by default; the switch exists so a test can run a
    # hundred logins without tripping it, and so an operator behind a proxy that
    # collapses every visitor onto one address can turn it off knowingly.
    rate_limit_enabled: bool = True

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

    # R scripts over a dataset.
    #
    # Off unless somebody turns it on, and deliberately so: an R script is a
    # program, not an expression, and it runs with the permissions of the
    # process serving this platform. The timeout and the memory cap stop a
    # runaway script; nothing here stops a hostile one, and pretending
    # otherwise would be worse than saying so. Turn it on where the people who
    # can run R in a project are the people you would trust with a shell.
    r_scripts_enabled: bool = False
    r_binary: str = "Rscript"
    r_timeout_seconds: int = 60
    r_memory_mb: int = 2048

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

    @property
    def boundaries_path(self) -> Path:
        return self.storage_path / "boundaries"

    @property
    def duckdb_temp_path(self) -> Path:
        if self.duckdb_temp_dir:
            return Path(self.duckdb_temp_dir)
        return self.storage_path / "duckdb_tmp"

    @property
    def workspaces_path(self) -> Path:
        """Where each project's R workspace lives.

        Kept between runs on purpose: a project is an environment, so an object
        saved with saveRDS, a lookup table written to disk, or a package
        installed into the project's own library is still there next time.
        """
        return self.storage_path / "workspaces"

    def ensure_directories(self) -> None:
        for path in (
            self.datasets_path,
            self.uploads_path,
            self.exports_path,
            self.boundaries_path,
            self.workspaces_path,
            self.duckdb_temp_path,
        ):
            path.mkdir(parents=True, exist_ok=True)

    @property
    def mail_enabled(self) -> bool:
        return bool(self.smtp_host)

    def validate_security_settings(self) -> None:
        if self.environment.lower() in NON_PRODUCTION_ENVIRONMENTS:
            return
        problems: list[str] = []
        if self.secret_key in DEFAULT_SECRET_KEYS:
            problems.append("SECRET_KEY is using an insecure default value")
        if self.first_admin_email.lower() in DEFAULT_FIRST_ADMIN_EMAILS:
            problems.append("FIRST_ADMIN_EMAIL is using a default placeholder")
        if self.first_admin_password in DEFAULT_FIRST_ADMIN_PASSWORDS:
            problems.append("FIRST_ADMIN_PASSWORD is using a default placeholder")
        if problems:
            raise ValueError(
                "Unsafe production configuration: "
                + "; ".join(problems)
                + ". Set strong non-default values before starting the application."
            )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
