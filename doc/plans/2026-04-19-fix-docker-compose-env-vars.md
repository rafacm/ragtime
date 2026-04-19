# Fix docker-compose.yml to read DB credentials from .env

**Date:** 2026-04-19

## Context

`docker-compose.yml` hard-codes `POSTGRES_DB=ragtime`, `POSTGRES_USER=ragtime`, `POSTGRES_PASSWORD=ragtime`, and the published port `5432`. The same values are also declared in `.env.sample` as `RAGTIME_DB_*` and can be edited in `.env` or set via `manage.py configure`. A user who changes the DB name, user, password, or port in `.env` ends up with a Postgres container that ignores those overrides — the Django app then fails to connect because its credentials no longer match what the container was initialized with.

## Approach

Replace the hard-coded values in `docker-compose.yml` with Compose variable substitution, using the existing `RAGTIME_DB_*` names so no new env vars are introduced. Compose auto-loads `.env` from the project directory, so any value the user sets in `.env` flows through automatically. Fall back to `ragtime` / `5432` as literal defaults so `docker compose up` still works in a freshly cloned repo with no `.env`.

## Changes

1. **`docker-compose.yml`** — use `${RAGTIME_DB_NAME:-ragtime}`, `${RAGTIME_DB_USER:-ragtime}`, `${RAGTIME_DB_PASSWORD:-ragtime}`, and `${RAGTIME_DB_PORT:-5432}` for the `POSTGRES_*` environment entries, the published host port, and the `pg_isready -U` flag in the healthcheck. Apply the same treatment to Qdrant's published HTTP port via `${RAGTIME_QDRANT_PORT:-6333}` (gRPC port `6334` stays hardcoded since no env var exists for it). Rename the `db` service to `postgres` to match the image name and the existing `.github/workflows/ci.yml` service name.
2. **`.env.sample`** — update the DB section header comment from "defaults match docker-compose.yml" to note that docker-compose reads these values. Apply the same update to the Qdrant section comment.
3. **`README.md`** — restructure "Getting Started" so Configuration comes before services start: **Installation** (`git clone` + `uv sync`), **Configuration** (wizard or `.env.sample` copy, with an explicit note that `RAGTIME_DB_*` and `RAGTIME_QDRANT_PORT` feed docker-compose), **Running the services** (`docker compose up -d`, `migrate`, `createsuperuser`, `load_entity_types`, `runserver`, `qcluster`).
4. **Archival doc updates** — update the `docker compose up -d qdrant db` command in `doc/features/2026-04-19-embed-step.md` and `doc/plans/2026-04-19-embed-step.md` to `postgres qdrant` so the instructions still work after the service rename.
5. **`CHANGELOG.md`** — add a `### Fixed` entry under `## 2026-04-19` linking to the plan, feature doc, and both session transcripts.
6. **Docs** — new plan, feature, and session transcripts under `doc/`.

## Non-goals

- No new env vars.
- `RAGTIME_DB_HOST` is not referenced by the Compose file (the container always listens on its own hostname, which becomes `postgres` after the rename); `.env` uses it to tell Django where to connect and that stays unchanged.
- The `manage.py configure` wizard already writes `RAGTIME_DB_*` — no changes needed there.

## Verification

1. `docker compose config` with no `.env` → resolves to the current defaults (`ragtime` / `ragtime` / `ragtime` / port `5432`).
2. `RAGTIME_DB_NAME=testdb RAGTIME_DB_USER=testuser RAGTIME_DB_PASSWORD=testpass RAGTIME_DB_PORT=5433 docker compose config` → resolves to the overridden values for `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, the published port, and `pg_isready -U`.
3. Branching: dedicated branch off `main`, PR via rebase strategy.
