# Fix docker-compose.yml to read DB credentials from .env

**Date:** 2026-04-19

## Context

`docker-compose.yml` hard-codes `POSTGRES_DB=ragtime`, `POSTGRES_USER=ragtime`, `POSTGRES_PASSWORD=ragtime`, and the published port `5432`. The same values are also declared in `.env.sample` as `RAGTIME_DB_*` and can be edited in `.env` or set via `manage.py configure`. A user who changes the DB name, user, password, or port in `.env` ends up with a Postgres container that ignores those overrides — the Django app then fails to connect because its credentials no longer match what the container was initialized with.

## Approach

Replace the hard-coded values in `docker-compose.yml` with Compose variable substitution, using the existing `RAGTIME_DB_*` names so no new env vars are introduced. Compose auto-loads `.env` from the project directory, so any value the user sets in `.env` flows through automatically. Fall back to `ragtime` / `5432` as literal defaults so `docker compose up` still works in a freshly cloned repo with no `.env`.

## Changes

1. **`docker-compose.yml`** — use `${RAGTIME_DB_NAME:-ragtime}`, `${RAGTIME_DB_USER:-ragtime}`, `${RAGTIME_DB_PASSWORD:-ragtime}`, and `${RAGTIME_DB_PORT:-5432}` for the `POSTGRES_*` environment entries, the published host port, and the `pg_isready -U` flag in the healthcheck.
2. **`.env.sample`** — update the existing comment on the DB section from "defaults match docker-compose.yml" to note that docker-compose reads these values.
3. **`CHANGELOG.md`** — add a `### Fixed` entry under `## 2026-04-19` linking to the plan, feature doc, and both session transcripts.
4. **Docs** — new plan, feature, and session transcripts under `doc/`.

## Non-goals

- No new env vars.
- `RAGTIME_DB_HOST` is not referenced by the Compose file (the container always listens on its own hostname `db`); `.env` uses it to tell Django where to connect and that stays unchanged.
- The `manage.py configure` wizard already writes `RAGTIME_DB_*` — no changes needed there.

## Verification

1. `docker compose config` with no `.env` → resolves to the current defaults (`ragtime` / `ragtime` / `ragtime` / port `5432`).
2. `RAGTIME_DB_NAME=testdb RAGTIME_DB_USER=testuser RAGTIME_DB_PASSWORD=testpass RAGTIME_DB_PORT=5433 docker compose config` → resolves to the overridden values for `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, the published port, and `pg_isready -U`.
3. Branching: dedicated branch off `main`, PR via rebase strategy.
