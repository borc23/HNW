"""Lifecycle of build_adapters: cleanup runs on partial startup and on failing shutdown."""

from dataclasses import dataclass

import pytest

from housing_netherlands import wiring
from housing_netherlands.config import Settings


class FakeEngine:
    def __init__(self) -> None:
        self.disposed = False

    async def dispose(self) -> None:
        self.disposed = True


class FakeClosable:
    """Stands in for ArqJobQueue / S3BlobStore: only the lifecycle matters here."""

    def __init__(self, *, fail_on_close: bool = False) -> None:
        self.closed = False
        self.fail_on_close = fail_on_close

    async def close(self) -> None:
        self.closed = True
        if self.fail_on_close:
            raise RuntimeError("close failed")


class FakeSource(FakeClosable):
    def __init__(self, **kwargs: object) -> None:
        super().__init__()
        self.kwargs = kwargs


@dataclass
class Fakes:
    engine: FakeEngine
    queue: FakeClosable
    blobs: FakeClosable
    sources: list[FakeSource]


def _returning(obj: object):
    async def connect(*args: object, **kwargs: object) -> object:
        return obj

    return connect


def _raising(exc: Exception):
    async def connect(*args: object, **kwargs: object) -> object:
        raise exc

    return connect


@pytest.fixture
def fakes(monkeypatch: pytest.MonkeyPatch) -> Fakes:
    f = Fakes(FakeEngine(), FakeClosable(), FakeClosable(), [])
    monkeypatch.setattr(wiring, "create_engine", lambda url: f.engine)
    monkeypatch.setattr(wiring.ArqJobQueue, "connect", _returning(f.queue))
    monkeypatch.setattr(wiring.S3BlobStore, "connect", _returning(f.blobs))

    def make_source(**kwargs: object) -> FakeSource:
        f.sources.append(FakeSource(**kwargs))
        return f.sources[-1]

    monkeypatch.setattr(wiring, "HuurwoningenSource", make_source)
    return f


async def test_everything_closed_on_normal_exit(fakes: Fakes) -> None:
    settings = Settings(huurwoningen_timeout_s=5, huurwoningen_impersonate="safari")
    async with wiring.build_adapters(settings) as adapters:
        assert adapters.blobs is fakes.blobs
        assert adapters.sources == tuple(fakes.sources)
        assert fakes.sources[0].kwargs == {"timeout_s": 5, "impersonate": "safari"}
    assert fakes.blobs.closed and fakes.queue.closed and fakes.engine.disposed
    assert fakes.sources[0].closed


async def test_no_sources_when_none_enabled(fakes: Fakes) -> None:
    async with wiring.build_adapters(Settings(sources_enabled=[])) as adapters:
        assert adapters.sources == ()
    assert fakes.sources == []


async def test_engine_disposed_when_queue_connect_fails(
    fakes: Fakes, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(wiring.ArqJobQueue, "connect", _raising(ConnectionError("redis down")))
    with pytest.raises(ConnectionError, match="redis down"):
        async with wiring.build_adapters(Settings()):
            pytest.fail("should not start")
    assert fakes.engine.disposed


async def test_queue_and_engine_released_when_blob_connect_fails(
    fakes: Fakes, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(wiring.S3BlobStore, "connect", _raising(OSError("s3 down")))
    with pytest.raises(OSError, match="s3 down"):
        async with wiring.build_adapters(Settings()):
            pytest.fail("should not start")
    assert fakes.queue.closed and fakes.engine.disposed


async def test_all_cleanups_run_even_if_one_close_fails(
    fakes: Fakes, monkeypatch: pytest.MonkeyPatch
) -> None:
    fakes.queue.fail_on_close = True
    with pytest.raises(RuntimeError, match="close failed"):
        async with wiring.build_adapters(Settings()):
            pass
    assert fakes.blobs.closed and fakes.queue.closed and fakes.engine.disposed


async def test_cleanup_runs_when_body_raises(fakes: Fakes) -> None:
    with pytest.raises(ValueError, match="boom"):
        async with wiring.build_adapters(Settings()):
            raise ValueError("boom")
    assert fakes.blobs.closed and fakes.queue.closed and fakes.engine.disposed


async def test_unknown_queue_backend_fails_clearly_and_releases_engine(fakes: Fakes) -> None:
    # Bypasses validation, as if a backend were added to the Literal without a `case`.
    settings = Settings().model_copy(update={"queue_backend": "memory"})
    with pytest.raises(AssertionError, match="memory"):
        async with wiring.build_adapters(settings):
            pytest.fail("should not start")
    assert fakes.engine.disposed
