"""Point app settings at test-only resources, so integration tests never touch dev data."""

from urllib.parse import urlsplit

from sqlalchemy import make_url

from housing_netherlands.config import Settings

TEST_REDIS_DB = 15


def to_test_settings(settings: Settings) -> Settings:
    """Same services, separate resources: `<db>_test`, Redis db 15, `<bucket>-test`."""
    db_url = make_url(settings.database_url)
    return settings.model_copy(
        update={
            "database_url": db_url.set(database=f"{db_url.database}_test").render_as_string(
                hide_password=False
            ),
            "redis_url": urlsplit(settings.redis_url)._replace(path=f"/{TEST_REDIS_DB}").geturl(),
            "storage_bucket": f"{settings.storage_bucket}-test",
        }
    )
