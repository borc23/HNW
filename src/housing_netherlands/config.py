"""Application settings, read once from environment variables (and `.env` if present).

Every adapter choice and connection string lives here, so moving from the local
Docker Compose stack to managed cloud services is a config change, not a code change.
"""

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]


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

    # Object storage (S3 API: MinIO locally, S3 / R2 later)
    storage_endpoint: str | None = "http://localhost:9000"
    storage_bucket: str = "housing-raw"
    storage_region: str = "us-east-1"
    storage_access_key: SecretStr = SecretStr("minioadmin")
    storage_secret_key: SecretStr = SecretStr("minioadmin")

    llm_model_extract: str = "ollama_chat/qwen3.5:4b"
    llm_api_base: str | None = "http://localhost:11434"
    llm_timeout_s: float = Field(default=120.0, gt=0)

    # listing sources allowed to run; comma-separated in the env
    sources_enabled: Annotated[list[str], NoDecode] = ["huurwoningen"]

    @field_validator("sources_enabled", mode="before")
    @classmethod
    def _split_sources(cls, value: object) -> object:
        if isinstance(value, str):
            return [s.strip().lower() for s in value.split(",") if s.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
