# Switch from SQLite to PostgreSQL with Docker Compose

**Date:** 2026-03-23

## Context

Django Q2 workers run pipeline steps in parallel, causing `sqlite3.OperationalError: database is locked` errors. SQLite only supports one writer at a time. PostgreSQL handles concurrent writes natively.

## Approach

Introduce Docker Compose for PostgreSQL, keep the Django app running locally via `uv run`. Add `manage.py dbreset` for easy database reset. PostgreSQL-only (no SQLite fallback).

## Changes

| File | Change |
|------|--------|
| `docker-compose.yml` | New — PostgreSQL 17 Alpine, localhost-only port |
| `pyproject.toml` | Add `psycopg[binary]` |
| `ragtime/settings.py` | Switch to postgresql backend with `RAGTIME_DB_*` env vars |
| `.env.sample` | Add `RAGTIME_DB_*` vars |
| `core/management/commands/_configure_helpers.py` | Add Database system |
| `core/management/commands/dbreset.py` | New — database reset command |
| `.github/workflows/ci.yml` | Add PostgreSQL service container |
| `ragtime/test_runner.py` | New — terminate lingering connections before DROP |
| `doc/README.md` | Development section with prerequisites, services, testing |
| `README.md` | Updated Getting Started with Docker prerequisite |
