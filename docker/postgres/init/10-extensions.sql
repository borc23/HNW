-- Runs once, on first start with an empty data volume.
-- Alembic migrations also create these (IF NOT EXISTS), so managed Postgres works the same way.
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS vector;
