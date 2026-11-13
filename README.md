# housing-netherlands

Personal housing dashboard for the Dutch rental market: collects, enriches and ranks listings.

The worker keeps every huurwoningen.nl listing in Rotterdam in step: every 15 minutes it reads
the site's sitemap, imports new and changed listings (raw page archived, listing parsed and
stored) and hides listings that are no longer offered. English AI summaries with three key
facts are written in the background, one at a time, newest first. You can still import a single
listing by URL (it is summarised straight away). Scraped sources are for personal use only.

## Run it

Needs Docker with Compose v2.24+. Everything runs locally, the LLM included (Ollama, CPU).

```bash
cp .env.example .env
docker compose up -d --build --wait api worker
```

The first start pulls the LLM (`qwen3.5:4b`, ~3 GB). If Ollama already runs on your machine on
port 11434, stop it or set `OLLAMA_PORT` in `.env`.

Open **http://localhost:8000**, paste a listing URL (e.g. from huurwoningen.nl/in/rotterdam) and
click **Import**. The page shows the job; click **refresh** until it says `succeeded`. On a CPU
the summary takes about a minute; importing the same listing again reuses it (well under a
second).

| Service | What it does |
|---|---|
| `api` | FastAPI on `localhost:8000`: the page and the JSON API |
| `worker` | arq worker: imports listings; syncs Rotterdam every 15 min; writes summaries in the background; sweeps stuck jobs every minute |
| `migrate` | one-shot `alembic upgrade head` before `api` and `worker` start |
| `postgres` `redis` `seaweedfs` `ollama` | database (PostGIS + pgvector), queue, S3 raw pages, LLM |

### Web app

The feed lives in `web/` (Next.js). It talks to the API above from the server side, so the API
URL is plain configuration (`API_URL`, default `http://localhost:8000`; see `web/.env.example`).

```bash
cd web
npm install
npm run dev          # http://localhost:3000
```

### JSON API

```bash
curl -X POST localhost:8000/api/listings/import -H 'content-type: application/json' \
     -d '{"url": "https://www.huurwoningen.nl/huren/rotterdam/<id>/<street>/"}'   # {"job_id": ...}
curl localhost:8000/api/jobs/<job_id>          # queued | running | succeeded | failed (+ error)
curl "localhost:8000/api/listings?limit=10"    # listings with their summary
```

### Logs

JSON lines; every line of a request or job carries its `request_id` / `job_id`.

```bash
docker compose logs -f worker api
```

## Configuration

All settings are environment variables (`.env`); see `.env.example`. Common ones:

| Variable | Default | Notes |
|---|---|---|
| `LLM_MODEL_EXTRACT` | `ollama_chat/qwen3.5:4b` | Any LiteLLM model string; e.g. `anthropic/claude-haiku-5-5` (+ `ANTHROPIC_API_KEY`). No code change. |
| `LLM_REASONING_EFFORT` | `none` | `none` turns off "thinking" (much faster on CPU); empty = model default |
| `SOURCES_ENABLED` | `huurwoningen` | Comma-separated |
| `HUURWONINGEN_IMPERSONATE` | `chrome` | Browser profile for the site's bot check; checked at startup |
| `IMPORT_MAX_ATTEMPTS` | `3` | Temporary failures (site down, LLM unreachable) retry after 30 s, 60 s |
| `SYNC_CITY` | `rotterdam` | City to mirror; empty turns the scheduled sync off |
| `SYNC_EVERY_MIN` | `15` | Minutes between syncs (one sitemap request each) |
| `HUURWONINGEN_MIN_INTERVAL_S` | `2` | Seconds between requests to the site; a full backfill (~1,500 pages) takes about an hour |
| `SUMMARY_BATCH_S` | `240` | Seconds of LLM work per background run; about one summary a minute on CPU |

## Development

Requires [uv](https://docs.astral.sh/uv/) and Python 3.12.

```bash
uv sync
uv run pre-commit install
uv run pytest -m "not integration"           # unit tests, no services needed
docker compose up -d --wait postgres redis seaweedfs
uv run pytest                                # everything, incl. the end-to-end test
uv run pyright                               # type check
```

Integration tests use separate resources (`housing_test` database, Redis db 15, bucket
`housing-raw-test`), so they never touch your data. They skip when a service is down, except
on CI. The live-LLM test runs only when Ollama is reachable. Tests against the real
huurwoningen.nl (`tests/live/`) never run unless you opt in: `RUN_LIVE_TESTS=1 uv run pytest tests/live`.

Layout: `core/` (domain, use-cases, ports; no infrastructure imports), `adapters/` (Postgres,
Redis/arq, S3, LiteLLM, huurwoningen), `wiring.py` (picks adapters from settings), `api/`,
`workers/`. A test enforces those import boundaries.

## CI

GitHub Actions on pushes to `main` and `dev` and on pull requests: ruff, pyright, unit tests,
and the integration tests against Postgres, Redis and SeaweedFS from `docker-compose.yml`.
