import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from pydantic import SecretStr

from housing_netherlands.adapters.blob_s3 import S3BlobStore
from housing_netherlands.config import Settings
from housing_netherlands.core import ports
from housing_netherlands.wiring import connect_blob_store


@asynccontextmanager
async def opened(settings: Settings) -> AsyncIterator[S3BlobStore]:
    store = await connect_blob_store(settings)
    try:
        yield store
    finally:
        await store.close()


@pytest.fixture
async def blobs(s3_settings: Settings) -> AsyncIterator[S3BlobStore]:
    async with opened(s3_settings) as store:
        yield store


@pytest.fixture
def key() -> str:
    return f"test/{uuid.uuid4().hex}.json"


def test_implements_port(blobs: S3BlobStore) -> None:
    assert isinstance(blobs, ports.BlobStore)


async def test_put_then_get_round_trip(blobs: S3BlobStore, key: str) -> None:
    data = b'{"title": "Appartement Zuidplein", "price": 915}'
    await blobs.put(key, data, "application/json")
    assert await blobs.get(key) == data


async def test_put_overwrites(blobs: S3BlobStore, key: str) -> None:
    await blobs.put(key, b"v1", "text/plain")
    await blobs.put(key, b"v2", "text/plain")
    assert await blobs.get(key) == b"v2"


async def test_missing_key_raises_key_error(blobs: S3BlobStore, key: str) -> None:
    with pytest.raises(KeyError):
        await blobs.get(key)


async def test_one_client_serves_many_calls(blobs: S3BlobStore) -> None:
    keys = [f"test/many-{uuid.uuid4().hex}-{i}" for i in range(20)]
    for i, k in enumerate(keys):
        await blobs.put(k, str(i).encode(), "text/plain")
    assert [await blobs.get(k) for k in keys] == [str(i).encode() for i in range(20)]


async def test_calls_fail_after_close(s3_settings: Settings, key: str) -> None:
    store = await connect_blob_store(s3_settings)
    await store.close()
    with pytest.raises(RuntimeError, match="closed"):
        await store.put(key, b"x", "text/plain")


async def test_wrong_credentials_are_rejected(s3_settings: Settings, key: str) -> None:
    bad_settings = s3_settings.model_copy(update={"storage_secret_key": SecretStr("x")})
    auth_errors = r"SignatureDoesNotMatch|AccessDenied|InvalidAccessKeyId"
    async with opened(bad_settings) as bad:
        with pytest.raises(Exception, match=auth_errors):
            await bad.put(key, b"nope", "text/plain")


async def test_ensure_bucket_creates_missing_bucket_idempotently(s3_settings: Settings) -> None:
    name = f"housing-ensure-{uuid.uuid4().hex[:12]}"
    async with opened(s3_settings.model_copy(update={"storage_bucket": name})) as store:
        try:
            await store.ensure_bucket()
            await store.ensure_bucket()  # second call: bucket exists, no error
            await store.put("k", b"v", "text/plain")
            assert await store.get("k") == b"v"
        finally:
            await store._s3.delete_object(Bucket=name, Key="k")
            await store._s3.delete_bucket(Bucket=name)
