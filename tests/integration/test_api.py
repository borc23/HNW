"""The API with real adapters (test Postgres/Redis/S3) through `wiring.build_adapters`."""

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from housing_netherlands.adapters.queue_arq import ArqJobQueue
from housing_netherlands.config import Settings
from housing_netherlands.core.models import QueueJobState

URL = "https://www.huurwoningen.nl/huren/rotterdam/ea81e68d/zuidplein/"


async def test_import_is_logged_and_queued_on_test_resources(
    client: TestClient, s3_settings: Settings, sessions: async_sessionmaker[AsyncSession]
) -> None:
    response = client.post("/api/listings/import", json={"url": URL})
    assert response.status_code == 202
    job_id = response.json()["job_id"]

    assert client.get(f"/api/jobs/{job_id}").json()["status"] == "queued"
    async with sessions() as s:
        assert await s.scalar(text("SELECT current_database()")) == "housing_test"
        query = text("SELECT status FROM jobs_log WHERE id = :id")
        assert await s.scalar(query, {"id": job_id}) == "queued"
    queue = await ArqJobQueue.connect(s3_settings.redis_url)
    try:
        assert (await queue.job_info(job_id)).state is QueueJobState.PENDING
    finally:
        await queue.close()


def test_page_renders_with_real_adapters(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200 and "<h1>NL Housing</h1>" in response.text
