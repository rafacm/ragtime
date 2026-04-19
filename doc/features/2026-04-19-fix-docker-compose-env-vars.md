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

The comment at the top of the DB section in `.env.sample` was updated from "defaults match docker-compose.yml" to note that docker-compose reads these values, since the relationship is now explicit rather than coincidental.

### README restructure

The "Getting Started" section was reorganized so the causal chain is visible on the page: configure first, then docker compose picks up those values, then start Django. It now has three subsections:

1. **Installation** — `git clone` + `uv sync`. No service startup yet.
2. **Configuration** — run `manage.py configure` (or copy `.env.sample` to `.env`). Explicit note that `RAGTIME_DB_*` are read by `docker-compose.yml`, with defaults (`ragtime` / port `5432`) when unset.
3. **Running the services** — `docker compose up -d`, `migrate`, `createsuperuser`, `load_entity_types`, `runserver`, `qcluster`. The `docker compose up -d` line carries an inline comment noting it reads `RAGTIME_DB_*` from `.env`.

Previously the wizard ran near the end — after the database container had already been initialized — so any DB customization had no effect without manual container recreation. The new order removes that footgun.

## Key parameters

| Variable | Default | Used for |
|---|---|---|
| `RAGTIME_DB_NAME` | `ragtime` | `POSTGRES_DB` |
| `RAGTIME_DB_USER` | `ragtime` | `POSTGRES_USER` and `pg_isready -U` |
| `RAGTIME_DB_PASSWORD` | `ragtime` | `POSTGRES_PASSWORD` |
| `RAGTIME_DB_PORT` | `5432` | Published host port |

`RAGTIME_DB_HOST` is deliberately not referenced by the Compose file — the Postgres container always listens on the internal Compose hostname `db`; `.env` uses `RAGTIME_DB_HOST` only to tell Django where to connect, which is unchanged.

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
   docker compose config
   ```
   → values propagate to all four substitution points (including `pg_isready -U testuser`).

3. `uv run python manage.py test` — no code changes; tests should pass unchanged.

## Files modified

| File | Change |
|---|---|
| `docker-compose.yml` | Replaced hard-coded DB name/user/password/port with `${RAGTIME_DB_*}` substitutions (with literal defaults). |
| `.env.sample` | Updated the DB section header comment to note docker-compose reads these values. |
| `README.md` | Restructured "Getting Started" into Installation / Configuration / Running the services so configure runs before `docker compose up`. |
| `CHANGELOG.md` | Added 2026-04-19 `### Fixed` entry. |
| `doc/plans/2026-04-19-fix-docker-compose-env-vars.md` | **New** — plan document. |
| `doc/features/2026-04-19-fix-docker-compose-env-vars.md` | **New** — this file. |
| `doc/sessions/2026-04-19-fix-docker-compose-env-vars-planning-session.md` | **New** — planning session transcript. |
| `doc/sessions/2026-04-19-fix-docker-compose-env-vars-implementation-session.md` | **New** — implementation session transcript. |
