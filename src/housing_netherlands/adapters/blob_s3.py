import asyncio
from contextlib import AsyncExitStack
from typing import TYPE_CHECKING, Any, Self

import aioboto3
from aiobotocore.config import AioConfig
from botocore.exceptions import ClientError

if TYPE_CHECKING:  # stubs are a dev dependency (types-aioboto3[s3])
    from types_aiobotocore_s3 import S3Client

# Upper bound on botocore's backoff between attempts, added to the per-call deadline.
_BACKOFF_MARGIN_S = 5.0


def _drop_expect_continue(request: Any, **_: Any) -> None:
    """botocore sends `Expect: 100-continue` on PutObject and waits for "100 Continue" before
    the body; aiohttp's wait for it ignores read_timeout, so a hung server would block forever.
    Dropping it sends the body right away. Safe for SigV4: botocore never signs `Expect`."""
    request.headers.pop("Expect", None)


class S3BlobStore:
    """`BlobStore` on one long-lived S3 client (connection pool reused across calls).

    Create with `await S3BlobStore.connect(...)` and release with `await store.close()`.
    Every call is bounded: connect/read timeouts per attempt, plus an overall deadline.
    """

    def __init__(
        self,
        client: "S3Client",
        stack: AsyncExitStack,
        *,
        bucket: str,
        region: str,
        call_timeout_s: float,
    ) -> None:
        self._client = client
        self._stack = stack
        self._closed = False
        self._bucket = bucket
        self._region = region
        self._call_timeout_s = call_timeout_s

    @classmethod
    async def connect(
        cls,
        *,
        bucket: str,
        endpoint_url: str | None,
        region: str,
        access_key: str,
        secret_key: str,
        connect_timeout_s: float = 3.0,
        read_timeout_s: float = 10.0,
        max_attempts: int = 2,
    ) -> Self:
        """Open the client. Timeouts bound a hung server (botocore defaults are 60 s each);
        `max_attempts` counts the first try, so 1 means no retries."""
        session = aioboto3.Session(
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
        )
        config = AioConfig(
            # Path-style URLs (endpoint/bucket/key): needed by SeaweedFS, fine for AWS.
            s3={"addressing_style": "path"},
            connect_timeout=connect_timeout_s,
            read_timeout=read_timeout_s,
            retries={"mode": "standard", "total_max_attempts": max_attempts},
        )
        stack = AsyncExitStack()
        client = await stack.enter_async_context(
            session.client("s3", endpoint_url=endpoint_url, config=config)
        )
        client.meta.events.register("before-send.s3", _drop_expect_continue)
        call_timeout_s = max_attempts * (connect_timeout_s + read_timeout_s) + _BACKOFF_MARGIN_S
        return cls(client, stack, bucket=bucket, region=region, call_timeout_s=call_timeout_s)

    async def close(self) -> None:
        self._closed = True
        await self._stack.aclose()

    @property
    def _s3(self) -> "S3Client":
        # aiobotocore silently reopens HTTP sessions on a closed client, which would leak them.
        if self._closed:
            raise RuntimeError("S3BlobStore is closed")
        return self._client

    async def ensure_bucket(self) -> None:
        """Create the bucket if it doesn't exist (idempotent). Local dev and tests only:
        in AWS the bucket is created by infrastructure-as-code."""
        async with asyncio.timeout(self._call_timeout_s):
            try:
                await self._s3.head_bucket(Bucket=self._bucket)
                return
            except ClientError as exc:
                if exc.response.get("Error", {}).get("Code") not in ("404", "NoSuchBucket"):
                    raise
            if self._region == "us-east-1":
                await self._s3.create_bucket(Bucket=self._bucket)
            else:
                await self._s3.create_bucket(
                    Bucket=self._bucket,
                    CreateBucketConfiguration={"LocationConstraint": self._region},  # type: ignore[typeddict-item]
                )

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        async with asyncio.timeout(self._call_timeout_s):
            await self._s3.put_object(
                Bucket=self._bucket, Key=key, Body=data, ContentType=content_type
            )

    async def get(self, key: str) -> bytes:
        """Return the object's bytes; raise `KeyError` if it doesn't exist."""
        async with asyncio.timeout(self._call_timeout_s):
            try:
                response = await self._s3.get_object(Bucket=self._bucket, Key=key)
            except ClientError as exc:
                if exc.response.get("Error", {}).get("Code") in ("NoSuchKey", "404"):
                    raise KeyError(key) from exc
                raise
            async with response["Body"] as body:
                return await body.read()
