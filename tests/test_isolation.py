from sqlalchemy import make_url

from housing_netherlands.config import Settings
from tests.isolation import to_test_settings

DEV = Settings(
    database_url="postgresql+asyncpg://housing:secret@localhost:5432/housing",
    redis_url="redis://localhost:6379/0",
    storage_bucket="housing-raw",
)


def test_every_stateful_resource_is_separate_from_dev() -> None:
    test = to_test_settings(DEV)
    assert make_url(test.database_url).database == "housing_test"
    assert test.redis_url == "redis://localhost:6379/15"
    assert test.storage_bucket == "housing-raw-test"


def test_only_resource_names_change() -> None:
    test = to_test_settings(DEV)
    db, dev_db = make_url(test.database_url), make_url(DEV.database_url)
    assert (db.host, db.port, db.username, db.password) == (
        dev_db.host,
        dev_db.port,
        dev_db.username,
        dev_db.password,
    )
    assert test.storage_endpoint == DEV.storage_endpoint
    assert test.llm_model_extract == DEV.llm_model_extract


def test_redis_url_without_db_path() -> None:
    test = to_test_settings(DEV.model_copy(update={"redis_url": "redis://redis:6379"}))
    assert test.redis_url == "redis://redis:6379/15"
