"""Alembic environment (async). URL: `-x database_url=...`, else the app's DATABASE_URL setting."""

import asyncio
from logging.config import fileConfig

from alembic import context
from geoalchemy2 import alembic_helpers
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from housing_netherlands.adapters.db.models import Base
from housing_netherlands.config import get_settings

config = context.config
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
    return (
        context.get_x_argument(as_dictionary=True).get("database_url")
        or config.attributes.get("database_url")
        or get_settings().database_url
    )


def _configure(**kwargs: object) -> None:
    context.configure(
        target_metadata=target_metadata,
        include_object=alembic_helpers.include_object,
        process_revision_directives=alembic_helpers.writer,
        render_item=alembic_helpers.render_item,
        compare_type=True,
        **kwargs,
    )


def run_migrations_offline() -> None:
    _configure(url=_database_url(), literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def _run_sync(connection: Connection) -> None:
    _configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(_database_url())
    async with engine.connect() as connection:
        await connection.run_sync(_run_sync)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
