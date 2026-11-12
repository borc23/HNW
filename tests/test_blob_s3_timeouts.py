"""S3 timeouts against a local server that accepts connections but never answers (no Compose)."""

import asyncio
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

import pytest
from botocore.exceptions import ReadTimeoutError

from housing_netherlands.adapters.blob_s3 import S3BlobStore
from housing_netherlands.config import Settings
from housing_netherlands.wiring import connect_blob_store


@dataclass
class HungServer:
    url: str
    requests: list[bytes] = field(default_factory=list)  # raw request heads, one per connection


@pytest.fixture
async def hung() -> AsyncIterator[HungServer]:
    """An HTTP endpoint that reads requests but never replies."""
    stop = asyncio.Event()
    server_state = HungServer(url="")

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        server_state.requests.append(await reader.read(65536))
        await stop.wait()  # hold the connection open without replying until teardown
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    server_state.url = f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}"
    yield server_state
    stop.set()
    server.close()
    await asyncio.wait_for(server.wait_closed(), 5)


async def _store(url: str, **overrides: object) -> S3BlobStore:
    return await connect_blob_store(Settings(storage_endpoint=url, **overrides))  # type: ignore[arg-type]


@pytest.mark.parametrize("op", ["get", "put"])
async def test_hung_server_fails_after_timeout_x_attempts(hung: HungServer, op: str) -> None:
    store = await _store(hung.url, storage_read_timeout_s=0.3, storage_max_attempts=2)
    start = time.monotonic()
    try:
        with pytest.raises(ReadTimeoutError):
            if op == "get":
                await store.get("k")
            else:
                await store.put("k", b"v", "text/plain")
    finally:
        await store.close()

    assert len(hung.requests) == 2  # first try + one retry, then gives up
    assert time.monotonic() - start < 3  # ~2 x 0.3 s + backoff, not minutes


async def test_single_attempt_means_no_retry(hung: HungServer) -> None:
    store = await _store(hung.url, storage_read_timeout_s=0.3, storage_max_attempts=1)
    try:
        with pytest.raises(ReadTimeoutError):
            await store.put("k", b"v", "text/plain")
    finally:
        await store.close()
    assert len(hung.requests) == 1


async def test_put_sends_body_without_expect_continue(hung: HungServer) -> None:
    store = await _store(hung.url, storage_read_timeout_s=0.3, storage_max_attempts=1)
    try:
        with pytest.raises(ReadTimeoutError):
            await store.put("k", b"BODY", "text/plain")
    finally:
        await store.close()
    [request] = hung.requests
    assert b"expect:" not in request.lower()
    assert request.endswith(b"BODY")  # body sent straight away, no waiting for "100 Continue"


async def test_overall_deadline_bounds_a_call_that_never_returns() -> None:
    store = await _store("http://127.0.0.1:1")
    store._call_timeout_s = 0.2

    async def never(**_: object) -> None:
        await asyncio.Event().wait()

    store._client.put_object = never  # type: ignore[method-assign]
    try:
        with pytest.raises(TimeoutError):
            await store.put("k", b"v", "text/plain")
    finally:
        await store.close()


async def test_settings_reach_the_client() -> None:
    store = await _store(
        "http://127.0.0.1:1",
        storage_connect_timeout_s=1.5,
        storage_read_timeout_s=4.0,
        storage_max_attempts=3,
    )
    try:
        config = vars(store._client.meta.config)  # botocore sets these attributes dynamically
        assert (config["connect_timeout"], config["read_timeout"]) == (1.5, 4.0)
        assert config["retries"]["total_max_attempts"] == 3
        assert store._call_timeout_s == 3 * (1.5 + 4.0) + 5
    finally:
        await store.close()


def test_defaults_bound_the_worst_case() -> None:
    s = Settings()
    worst = s.storage_max_attempts * (s.storage_connect_timeout_s + s.storage_read_timeout_s)
    assert worst <= 30
