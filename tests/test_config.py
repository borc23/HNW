import pytest

from housing_netherlands.config import Settings


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    # Don't let a developer's real .env (or direnv-exported vars) leak into tests.
    monkeypatch.chdir(tmp_path)
    for name in Settings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)


def test_defaults_target_local_stack() -> None:
    s = Settings()
    assert s.database_url.startswith("postgresql+asyncpg://")
    assert s.queue_backend == "redis"
    assert s.sources_enabled == ["huurwoningen"]


def test_sources_enabled_parses_comma_separated_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SOURCES_ENABLED", " Huurwoningen , ,pasted_link")
    assert Settings().sources_enabled == ["huurwoningen", "pasted_link"]


def test_sources_enabled_can_be_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SOURCES_ENABLED", "")
    assert Settings().sources_enabled == []


def test_llm_model_switches_by_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_MODEL_EXTRACT", "anthropic/claude-haiku-5-5")
    assert Settings().llm_model_extract == "anthropic/claude-haiku-5-5"


def test_secrets_are_not_printed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STORAGE_SECRET_KEY", "super-secret")
    s = Settings()
    assert "super-secret" not in repr(s)
    assert s.storage_secret_key.get_secret_value() == "super-secret"


def test_reads_dotenv_file(tmp_path) -> None:
    (tmp_path / ".env").write_text("REDIS_URL=redis://cache:6379/1\n")
    assert Settings().redis_url == "redis://cache:6379/1"


@pytest.mark.parametrize("name", ["STORAGE_ENDPOINT", "OLLAMA_API_BASE"])
def test_empty_optional_url_means_unset(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    monkeypatch.setenv(name, "")
    assert getattr(Settings(), name.lower()) is None
