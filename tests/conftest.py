"""Tests marked `live` call real third-party websites. They never run unless asked for, so CI
and a plain `pytest` don't scrape anyone (scraped sources are for personal use only)."""

import os

import pytest

RUN_LIVE = os.getenv("RUN_LIVE_TESTS") == "1"


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    if RUN_LIVE:
        return
    skip = pytest.mark.skip(reason="live test against a real website; set RUN_LIVE_TESTS=1")
    for item in items:
        if item.get_closest_marker("live"):
            item.add_marker(skip)
