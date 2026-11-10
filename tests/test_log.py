import json

import pytest

from housing_netherlands.log import (
    bind_context,
    clear_context,
    configure_logging,
    get_logger,
    new_correlation_id,
)


@pytest.fixture(autouse=True)
def _clean_context():
    clear_context()
    yield
    clear_context()


def _last_json_line(out: str) -> dict:
    return json.loads(out.strip().splitlines()[-1])


def test_json_log_includes_bound_correlation_id(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO", json=True)
    request_id = new_correlation_id()
    bind_context(request_id=request_id)

    get_logger("test").info("listing.imported", listing_id=7)

    line = _last_json_line(capsys.readouterr().out)
    assert line["event"] == "listing.imported"
    assert line["request_id"] == request_id
    assert line["listing_id"] == 7
    assert line["level"] == "info"
    assert "timestamp" in line


def test_level_filter_drops_lower_levels(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("WARNING", json=True)
    get_logger().info("hidden")
    get_logger().warning("shown")
    out = capsys.readouterr().out
    assert "hidden" not in out
    assert _last_json_line(out)["event"] == "shown"


def test_correlation_ids_are_unique() -> None:
    assert new_correlation_id() != new_correlation_id()
