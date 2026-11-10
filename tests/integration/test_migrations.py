from alembic import command
from alembic.config import Config


def test_models_match_migrations(alembic_config: Config, migrated: None) -> None:
    # Fails if adapters/db/models.py drifted from the migrations (autogenerate would emit ops).
    command.check(alembic_config)


def test_downgrade_and_upgrade_round_trip(alembic_config: Config, migrated: None) -> None:
    command.downgrade(alembic_config, "base")
    command.upgrade(alembic_config, "head")
