"""FastAPI app: `uvicorn housing_netherlands.api.app:app`.

Requests only read and write data; the import itself runs in the worker.
"""

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from pathlib import Path
from typing import Annotated
from urllib.parse import urlencode

from fastapi import FastAPI, Form, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from housing_netherlands.config import get_settings
from housing_netherlands.core.errors import UnsupportedUrlError
from housing_netherlands.core.importing import request_import
from housing_netherlands.core.models import JobRecord, ListingView
from housing_netherlands.log import (
    bind_context,
    clear_context,
    configure_logging,
    get_logger,
    new_correlation_id,
)
from housing_netherlands.wiring import Adapters, build_adapters

log = get_logger(__name__)

AdaptersFactory = Callable[[], AbstractAsyncContextManager[Adapters]]
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")

Url = Annotated[str, Field(min_length=1, max_length=2048)]


class ImportRequest(BaseModel):
    url: Url


class ImportAccepted(BaseModel):
    job_id: str


def _real_adapters() -> AdaptersFactory:
    settings = get_settings()
    configure_logging(settings.log_level, json=settings.log_json)
    return lambda: build_adapters(settings)


def create_app(adapters_factory: AdaptersFactory | None = None) -> FastAPI:
    """Build the app; tests pass a factory that yields fake adapters."""
    factory = adapters_factory or _real_adapters()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with factory() as adapters:
            app.state.adapters = adapters
            yield

    app = FastAPI(title="NL Housing", lifespan=lifespan)

    @app.middleware("http")
    async def request_id(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        rid = request.headers.get("x-request-id") or new_correlation_id()
        clear_context()
        bind_context(request_id=rid)
        try:
            response = await call_next(request)
        finally:
            clear_context()
        response.headers["X-Request-ID"] = rid
        return response

    def adapters(request: Request) -> Adapters:
        return request.app.state.adapters

    async def queue_import(request: Request, url: str) -> str:
        a = adapters(request)
        job_id = await request_import(a.queue, a.job_log, a.sources, url.strip())
        log.info("import.requested", job_id=job_id, url=url)
        return job_id

    # --- JSON API ------------------------------------------------------------------------

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/listings/import", status_code=202)
    async def import_listing(request: Request, body: ImportRequest) -> ImportAccepted:
        try:
            return ImportAccepted(job_id=await queue_import(request, body.url))
        except UnsupportedUrlError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/jobs/{job_id}")
    async def get_job(request: Request, job_id: str) -> JobRecord:
        job = await adapters(request).job_log.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="job not found")
        return job

    @app.get("/api/listings")
    async def list_listings(
        request: Request, limit: Annotated[int, Query(ge=1, le=200)] = 50
    ) -> list[ListingView]:
        return await adapters(request).listings.list_listings(limit=limit)

    # --- plain HTML page for trying it out ------------------------------------------------

    @app.get("/", response_class=HTMLResponse)
    async def page(request: Request, job: str | None = None, error: str | None = None) -> Response:
        a = adapters(request)
        context = {
            "listings": await a.listings.list_listings(limit=50),
            "job": await a.job_log.get(job) if job else None,
            "error": error,
        }
        return templates.TemplateResponse(request, "index.html", context)

    @app.post("/import")
    async def import_form(request: Request, url: Annotated[Url, Form()]) -> RedirectResponse:
        try:
            query = {"job": await queue_import(request, url)}
        except UnsupportedUrlError as exc:
            query = {"error": str(exc)}
        return RedirectResponse(f"/?{urlencode(query)}", status_code=303)

    return app


app = create_app()
