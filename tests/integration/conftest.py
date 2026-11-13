import asyncio
import os
import socket
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import NoReturn

import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from redis.asyncio import Redis
from sqlalchemy import make_url, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.pool import NullPool

from housing_netherlands.adapters.db import create_engine, create_session_factory
from housing_netherlands.api.app import create_app
from housing_netherlands.config import Settings
from housing_netherlands.wiring import build_adapters, connect_blob_store
from tests.isolation import to_test_settings
from tests.service_probe import tcp_target

ROOT = Path(__file__).parents[2]
TABLES = "jobs_log, listing_enrichments, listings, properties"


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    here = Path(__file__).parent
    for item in items:
        if here in item.path.parents:
            item.add_marker(pytest.mark.integration)


async def _ensure_database(admin_url: str, name: str) -> None:
    engine = create_engine(admin_url, poolclass=NullPool, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as conn:
            exists = await conn.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": name}
            )
            if not exists:
                await conn.execute(text(f'CREATE DATABASE "{name}"'))
    finally:
        await engine.dispose()


@pytest.fixture(scope="session")
def database_url(test_settings: Settings) -> str:
    """URL of the test database, created (via the dev database's server) if missing."""
    test_url = make_url(test_settings.database_url)
    admin_url = Settings().database_url  # same server; only used to CREATE DATABASE
    try:
        asyncio.run(_ensure_database(admin_url, str(test_url.database)))
    except OSError as exc:
        unavailable("postgres", exc)
    return test_settings.database_url


def unavailable(service: str, exc: Exception) -> NoReturn:
    """Skip locally, fail on CI, when a Compose service isn't running."""
    reason = f"{service} not reachable ({exc}); run `docker compose up -d {service}`"
    if os.getenv("CI"):
        pytest.fail(reason, pytrace=False)
    pytest.skip(reason)


def require_tcp(service: str, url: str) -> None:
    """Skip/fail (see `unavailable`) unless `url`'s host accepts TCP; port defaults by scheme."""
    try:
        socket.create_connection(tcp_target(url), timeout=1).close()
    except OSError as exc:
        unavailable(service, exc)


@pytest.fixture(scope="session")
def test_settings() -> Settings:
    """App settings pointed at test-only resources; the only source of them (see isolation.py)."""
    return to_test_settings(Settings())


@pytest.fixture
async def redis_test_url(test_settings: Settings) -> AsyncIterator[str]:
    require_tcp("redis", test_settings.redis_url)
    client = Redis.from_url(test_settings.redis_url)
    await client.flushdb()
    yield test_settings.redis_url
    await client.flushdb()
    await client.aclose()


@pytest.fixture(scope="session")
def s3_settings(test_settings: Settings) -> Settings:
    """Test settings, with the test bucket on the local S3 created if missing."""
    if test_settings.storage_endpoint is None:
        # No endpoint means real AWS S3; these tests are for the local Compose S3 only.
        pytest.skip("STORAGE_ENDPOINT not set (AWS S3); S3 integration tests need local SeaweedFS")
    require_tcp("seaweedfs", test_settings.storage_endpoint)
    asyncio.run(_ensure_bucket(test_settings))
    return test_settings


async def _ensure_bucket(settings: Settings) -> None:
    store = await connect_blob_store(settings)
    try:
        await store.ensure_bucket()
    finally:
        await store.close()


@pytest.fixture(scope="session")
def alembic_config(database_url: str) -> Config:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.attributes["database_url"] = database_url
    cfg.attributes["configure_logger"] = False
    return cfg


@pytest.fixture(scope="session")
def migrated(alembic_config: Config) -> None:
    from alembic import command

    command.upgrade(alembic_config, "head")


@pytest.fixture
async def sessions(
    database_url: str, migrated: None
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_engine(database_url, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))
    yield create_session_factory(engine)
    await engine.dispose()


@pytest.fixture
def settings(s3_settings: Settings, redis_test_url: str) -> Settings:
    """Settings for app-level tests: every test resource ready, retry policy pinned (not .env)."""
    return s3_settings.model_copy(update={"import_max_attempts": 3})


@pytest.fixture
def client(settings: Settings, sessions: async_sessionmaker[AsyncSession]) -> Iterator[TestClient]:
    """The real app, built by `wiring.build_adapters` on the test resources (lifespan included)."""
    with TestClient(create_app(lambda: build_adapters(settings))) as c:
        yield c
