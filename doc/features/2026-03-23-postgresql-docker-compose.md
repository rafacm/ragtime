# Switch from SQLite to PostgreSQL with Docker Compose

**Date:** 2026-03-23

## Problem

Django Q2 workers processing pipeline steps in parallel caused `sqlite3.OperationalError: database is locked` errors. SQLite only allows one writer at a time, and the 30-second timeout was insufficient under concurrent workloads.

## Changes

### Docker Compose

Added `docker-compose.yml` with PostgreSQL 17 Alpine. Port bound to `127.0.0.1:5432` (localhost only, not exposed to the network). The `ragtime` database, user, and password are created automatically on first container start.

### Database backend

Switched `DATABASES` in `settings.py` from `sqlite3` to `postgresql`. Configured via `RAGTIME_DB_*` env vars with defaults matching the Docker Compose config for zero-config setup. Added `psycopg[binary]` to core dependencies.

### Database reset command

Added `manage.py dbreset` — drops and recreates the PostgreSQL database, runs migrations, seeds entity types. Supports `--yes` flag to skip confirmation. Connects to the `postgres` maintenance database to perform the DROP/CREATE.

### CI workflow

Added PostgreSQL 17 service container to the GitHub Actions CI workflow with the same credentials as `docker-compose.yml`.

### Test runner

Added `PostgresTestRunner` that patches `DatabaseCreation._destroy_test_db` to terminate lingering connections before `DROP DATABASE`. Some tests spawn async threads (via `asyncio.run` for the recovery agent) that create DB connections outliving the test.

### Langfuse session ID uniqueness

Added `YYYY-MM-DD-HH-MM` timestamps to `processing-run-*` and `recovery-run-*` Langfuse session IDs so they remain unique across database resets (auto-increment PKs restart from 1).

### Configuration wizard

Added Database system to the configure wizard with 5 fields: name, user, password (secret), host, port.

### Documentation

- Added Development section to `doc/README.md` with prerequisites, service startup, test running, and database reset instructions
- Added port conflict note for Langfuse users (their docker-compose.yml also uses port 5432)
- Updated README Getting Started with Docker prerequisite
- Updated Tech Stack to reference PostgreSQL

## Key Parameters

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| PostgreSQL version | 17 Alpine | Latest stable, small image |
| Port binding | `127.0.0.1:5432` | Localhost only for security |
| Default credentials | `ragtime/ragtime/ragtime` | Dev defaults, match Docker Compose |

## Verification

1. `docker compose up -d` — PostgreSQL starts and is healthy
2. `uv run python manage.py migrate` — migrations apply against PostgreSQL
3. `uv run python manage.py test` — all 243 tests pass, test DB tears down cleanly
4. `uv run python manage.py dbreset --yes` — drops/recreates DB successfully
5. Process 2+ episodes concurrently — no `database is locked` errors
6. Langfuse session IDs are unique across database resets

## Files Modified

| File | Change |
|------|--------|
| `docker-compose.yml` | New — PostgreSQL service |
| `pyproject.toml` | Added `psycopg[binary]>=3.2,<4` |
| `ragtime/settings.py` | PostgreSQL backend, `RAGTIME_DB_*` vars, `TEST_RUNNER` |
| `ragtime/test_runner.py` | New — PostgresTestRunner |
| `.env.sample` | Added `RAGTIME_DB_*` section |
| `.github/workflows/ci.yml` | Added PostgreSQL service container |
| `core/management/commands/_configure_helpers.py` | Added Database system |
| `core/management/commands/dbreset.py` | New — database reset command |
| `core/tests/test_configure.py` | Updated wizard tests for DB fields |
| `episodes/tests/test_summarize.py` | Fixed varchar test for PostgreSQL |
| `episodes/observability.py` | Timestamp in processing-run session ID |
| `episodes/agents/agent.py` | Timestamp in recovery-run session ID |
| `README.md` | Docker prerequisite, dbreset command |
| `CLAUDE.md` | Updated tech choice from SQLite to PostgreSQL |
| `doc/README.md` | Development section, Langfuse port conflict note |
