"""Application settings, read once from environment variables (and `.env` if present).

Every adapter choice and connection string lives here, so moving from the local
Docker Compose stack to managed cloud services is a config change, not a code change.
"""

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]
SourceName = Literal["huurwoningen"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Logging
    log_level: LogLevel = "INFO"
    log_json: bool = True

    # Database
    database_url: str = "postgresql+asyncpg://housing:housing@localhost:5432/housing"

    # Redis: cache, rate-limit counters, job queue
    redis_url: str = "redis://localhost:6379/0"
    queue_backend: Literal["redis"] = "redis"

    # Object storage (S3 API: SeaweedFS locally, S3 / R2 later)
    storage_endpoint: str | None = "http://localhost:8333"
    storage_bucket: str = "housing-raw"
    storage_region: str = "us-east-1"
    storage_access_key: SecretStr = SecretStr("housing")
    storage_secret_key: SecretStr = SecretStr("housing-secret")
    # Worst case per call ~= attempts x (connect + read) + backoff: 2 x (3 + 10) s ~= 30 s.
    storage_connect_timeout_s: float = Field(default=3.0, gt=0)
    storage_read_timeout_s: float = Field(default=10.0, gt=0)
    storage_max_attempts: int = Field(default=2, ge=1)  # total attempts, incl. the first

    llm_model_extract: str = "ollama_chat/qwen3.5:4b"
    # Only used for ollama/* models; hosted providers always use their own endpoint.
    ollama_api_base: str | None = "http://localhost:11434"
    llm_timeout_s: float = Field(default=120.0, gt=0)
    llm_reasoning_effort: str | None = "none"

    # listing sources allowed to run; comma-separated in the env
    sources_enabled: Annotated[list[SourceName], NoDecode] = ["huurwoningen"]

    # huurwoningen.nl (scraped: personal use only)
    huurwoningen_timeout_s: float = Field(default=20.0, gt=0)
    # curl_cffi browser profile, e.g. "chrome", "safari", "firefox"; change it if the site blocks
    huurwoningen_impersonate: str = "chrome"

    # Seconds between requests to the site from one worker (stay low-volume during backfills)
    huurwoningen_min_interval_s: float = Field(default=2.0, ge=0)

    # Scheduled sync: every SYNC_EVERY_MIN minutes, mirror SYNC_CITY from every enabled source
    # that can list its offer. Empty SYNC_CITY turns the sync off.
    sync_city: str | None = "rotterdam"
    sync_every_min: int = Field(default=15, ge=1, le=60)
    # Background summaries: each run (every minute) works this long, one LLM call at a time.
    summary_batch_s: float = Field(default=240.0, gt=0)

    # Import jobs: retryable fetch failures are retried with backoff (30 s, 60 s, ...).
    import_max_attempts: int = Field(default=3, ge=1)
    import_retry_base_delay_s: float = Field(default=30.0, ge=0)

    @field_validator(
        "storage_endpoint", "ollama_api_base", "llm_reasoning_effort", "sync_city", mode="before"
    )
    @classmethod
    def _empty_means_unset(cls, value: object) -> object:  # e.g. SYNC_CITY= turns the sync off
        # `STORAGE_ENDPOINT=` in .env means "no custom endpoint" (e.g. real AWS S3).
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("sources_enabled", mode="before")
    @classmethod
    def _split_sources(cls, value: object) -> object:
        if isinstance(value, str):
            # dict.fromkeys: drop duplicates, keep order
            return list(dict.fromkeys(s.strip().lower() for s in value.split(",") if s.strip()))
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
