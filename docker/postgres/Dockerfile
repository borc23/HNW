# Postgres 16 with PostGIS (geo) and pgvector (embeddings) in one image.
FROM postgis/postgis:16-3.6

RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-16-pgvector \
    && rm -rf /var/lib/apt/lists/*

COPY init/ /docker-entrypoint-initdb.d/
