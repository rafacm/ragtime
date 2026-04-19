# Session: Fix docker-compose.yml to read DB credentials from .env — Planning

**Date:** 2026-04-19

**Session ID:** 85c5300d-0f26-4d34-b9a9-02333c2f2312

## Summary

User noticed that `docker-compose.yml` hard-codes PostgreSQL credentials while the same values are also declared in `.env.sample` / `.env` and configurable via `manage.py configure`. Agreed on using Compose variable substitution with literal defaults so `.env` becomes the single source of truth without introducing any new env vars and without breaking a zero-config `docker compose up`.

## Conversation

### User

> In the docker-compose.yml there is an "environment:" entry for postgres containng the db, user and password. But this values are also defined in the ".env.sample" and ".env" file and configured via the configure command. Can we have the docker-compose.yml configuration get the values from the .env file too?

### Assistant

Read `docker-compose.yml` and `.env.sample` to confirm the duplication: Compose hard-codes `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, and the published port `5432`, while `.env.sample` already declares `RAGTIME_DB_NAME`, `RAGTIME_DB_USER`, `RAGTIME_DB_PASSWORD`, `RAGTIME_DB_HOST`, and `RAGTIME_DB_PORT`.

Proposed using Compose's native variable substitution (`${VAR:-default}`), which Docker Compose resolves against the auto-loaded `.env` file in the project directory. This approach:

- Introduces no new env vars — reuses the existing `RAGTIME_DB_*` names.
- Keeps `docker compose up` working with no `.env` present by providing literal defaults (`ragtime` / `5432`) that match the current hard-coded values.
- Touches four substitution points: the three `POSTGRES_*` lines, the published host port, and the `pg_isready -U` flag in the healthcheck (so the healthcheck also respects a custom user).

Noted that `RAGTIME_DB_HOST` is deliberately not referenced in Compose: the container always listens on the internal hostname `db`; `.env` uses `RAGTIME_DB_HOST` only to tell Django where to connect.

### User

> Make sure you use a worktree to make any changes

### Assistant

Acknowledged the project's worktree-first preference (also recorded in `feedback_worktree.md`). Entered a new worktree `fix/docker-compose-env-vars` before making any edits.

Wrote the edit to `docker-compose.yml`, then validated with `docker compose config` (no env: values resolved to `ragtime` / `5432`) and again with inline env overrides (`RAGTIME_DB_NAME=testdb`, etc.: values propagated correctly, including to the healthcheck).

Proposed also updating the stale top-of-section comment in `.env.sample` ("defaults match docker-compose.yml" → "docker-compose.yml reads these values") and committing.

### User

> yes

### Assistant

Updated `.env.sample` comment, created the plan, feature doc, and both session transcripts, added a `### Fixed` entry under `## 2026-04-19` in `CHANGELOG.md`, and prepared to commit on the worktree branch.
