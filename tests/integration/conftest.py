"""Integration fixtures: a dedicated `<db>_test` database on the Compose Postgres, migrated once.

Locally the tests skip when Postgres isn't running; on CI (`CI` env var set) they fail instead.
"""

import asyncio
import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import make_url, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.pool import NullPool

from housing_netherlands.adapters.db import create_engine, create_session_factory
from housing_netherlands.config import Settings

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
def database_url() -> str:
    base = make_url(Settings().database_url)
    test_url = base.set(database=f"{base.database}_test")
    try:
        asyncio.run(_ensure_database(base.render_as_string(hide_password=False), test_url.database))
    except OSError as exc:
        reason = f"Postgres not reachable ({exc}); run `docker compose up -d postgres`"
        if os.getenv("CI"):
            pytest.fail(reason, pytrace=False)
        pytest.skip(reason)
    return test_url.render_as_string(hide_password=False)


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
