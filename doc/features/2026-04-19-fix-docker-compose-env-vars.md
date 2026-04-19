# Fix docker-compose.yml to read DB credentials from .env

**Date:** 2026-04-19

## Problem

`docker-compose.yml` hard-coded the PostgreSQL database name, user, password, and published port. The same values were duplicated in `.env.sample` / `.env` as `RAGTIME_DB_*` and written by the `manage.py configure` wizard. A user who changed those values in `.env` would get a Postgres container initialized with the old hard-coded credentials, and Django would then fail to connect — silent drift between the two sources of truth.

## Changes

`docker-compose.yml` now uses Compose variable substitution with literal defaults, so `.env` becomes the single source of truth while a freshly cloned repo still runs with zero configuration:

```yaml
ports:
  - "127.0.0.1:${RAGTIME_DB_PORT:-5432}:5432"
environment:
  POSTGRES_DB: ${RAGTIME_DB_NAME:-ragtime}
  POSTGRES_USER: ${RAGTIME_DB_USER:-ragtime}
  POSTGRES_PASSWORD: ${RAGTIME_DB_PASSWORD:-ragtime}
# ...
healthcheck:
  test: ["CMD", "pg_isready", "-U", "${RAGTIME_DB_USER:-ragtime}"]
```

Docker Compose auto-loads `.env` from the project directory, so any value set there — whether by hand or by `manage.py configure` — flows through to the container. No new env vars were introduced; the `RAGTIME_DB_*` names were already defined in `.env.sample`.

The same treatment was applied to Qdrant: the published HTTP port now uses `${RAGTIME_QDRANT_PORT:-6333}`, so a user who overrides `RAGTIME_QDRANT_PORT` in `.env` gets both the published host port and the Django client (which reads the same var) on the same value. The gRPC port `6334` stays hard-coded since no matching env var exists in `.env.sample`.

The DB service was renamed from `db` to `postgres` to match the official image name and the service name already used in `.github/workflows/ci.yml`. The two archival doc commands that used `docker compose up -d qdrant db` (in `doc/features/2026-04-19-embed-step.md` and `doc/plans/2026-04-19-embed-step.md`) were updated to `qdrant postgres` so the instructions still work. The internal Compose hostname a container uses to reach Postgres also changes from `db` to `postgres`, but Django always connects from the host via `localhost:5432`, so no Django config needed changing.

The comments at the top of the DB and Qdrant sections in `.env.sample` were updated from "defaults match docker-compose.yml" to note that docker-compose reads these values, since the relationship is now explicit rather than coincidental.

### README restructure

The "Getting Started" section was reorganized so the causal chain is visible on the page: configure first, then docker compose picks up those values, then start Django. It now has three subsections:

1. **Installation** — `git clone` + `uv sync`. No service startup yet.
2. **Configuration** — run `manage.py configure` (or copy `.env.sample` to `.env`). Explicit bullets listing which `RAGTIME_*` vars feed docker-compose: `RAGTIME_DB_NAME/USER/PASSWORD/PORT` for Postgres (defaults `ragtime` / `5432`) and `RAGTIME_QDRANT_PORT` for Qdrant (default `6333`).
3. **Running the services** — `docker compose up -d`, `migrate`, `createsuperuser`, `load_entity_types`, `runserver`, `qcluster`. The `docker compose up -d` line carries an inline comment noting Postgres and Qdrant both read ports/creds from `.env`.

Previously the wizard ran near the end — after the database container had already been initialized — so any DB customization had no effect without manual container recreation. The new order removes that footgun.

## Key parameters

| Variable | Default | Used for |
|---|---|---|
| `RAGTIME_DB_NAME` | `ragtime` | `postgres` service: `POSTGRES_DB` |
| `RAGTIME_DB_USER` | `ragtime` | `postgres` service: `POSTGRES_USER` and `pg_isready -U` |
| `RAGTIME_DB_PASSWORD` | `ragtime` | `postgres` service: `POSTGRES_PASSWORD` |
| `RAGTIME_DB_PORT` | `5432` | `postgres` service: published host port |
| `RAGTIME_QDRANT_PORT` | `6333` | `qdrant` service: published host HTTP port |

`RAGTIME_DB_HOST` and `RAGTIME_QDRANT_HOST` are deliberately not referenced by the Compose file — containers always listen on their internal Compose hostnames (`postgres`, `qdrant`); `.env` uses these HOST vars only to tell Django where to connect, which is unchanged (`localhost` in local dev).

## Verification

1. Without any `.env` in the directory:
   ```bash
   docker compose config
   ```
   → `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` all resolve to `ragtime`, published port is `5432`, and `pg_isready -U ragtime`.

2. With overrides:
   ```bash
   RAGTIME_DB_NAME=testdb RAGTIME_DB_USER=testuser \
   RAGTIME_DB_PASSWORD=testpass RAGTIME_DB_PORT=5433 \
   RAGTIME_QDRANT_PORT=7333 \
   docker compose config
   ```
   → values propagate to all five substitution points (including `pg_isready -U testuser` and the published Qdrant HTTP port).

3. `uv run python manage.py test` — no code changes; tests should pass unchanged.

## Files modified

| File | Change |
|---|---|
| `docker-compose.yml` | Replaced hard-coded DB name/user/password/port with `${RAGTIME_DB_*}` substitutions; parameterized Qdrant HTTP port with `${RAGTIME_QDRANT_PORT:-6333}`; renamed `db` service to `postgres`. |
| `.env.sample` | Updated the DB and Qdrant section header comments to note docker-compose reads these values. |
| `README.md` | Restructured "Getting Started" into Installation / Configuration / Running the services so configure runs before `docker compose up`. Configuration paragraph now lists both Postgres and Qdrant vars that feed docker-compose. |
| `doc/features/2026-04-19-embed-step.md` | Updated `docker compose up -d qdrant db` → `qdrant postgres` to track the service rename. |
| `doc/plans/2026-04-19-embed-step.md` | Same rename as above. |
| `CHANGELOG.md` | Added 2026-04-19 `### Fixed` entry. |
| `doc/plans/2026-04-19-fix-docker-compose-env-vars.md` | **New** — plan document. |
| `doc/features/2026-04-19-fix-docker-compose-env-vars.md` | **New** — this file. |
| `doc/sessions/2026-04-19-fix-docker-compose-env-vars-planning-session.md` | **New** — planning session transcript. |
| `doc/sessions/2026-04-19-fix-docker-compose-env-vars-implementation-session.md` | **New** — implementation session transcript. |
