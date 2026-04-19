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

Updated `.env.sample` comment, created the plan, feature doc, and both session transcripts, added a `### Fixed` entry under `## 2026-04-19` in `CHANGELOG.md`, and committed on the worktree branch.

### User

> In the current README. The Configuration section is after Installation. I would like to re-structure the section to be more clear. Maybe we can move the Configuration before so that it is clear then that whatever values for the PostgreSQL database will then be used when starting docker compose.

### Assistant

Noted the wrinkle that `manage.py configure` requires the code cloned and `uv sync` run first, so Configuration cannot literally precede all Installation. Proposed a three-subsection split:

1. **Installation** — `git clone` + `uv sync` (code setup only).
2. **Configuration** — wizard or `.env.sample` copy, with a note that `RAGTIME_DB_*` feeds docker-compose.
3. **Running the services** — `docker compose up -d`, `migrate`, `createsuperuser`, `load_entity_types`, `runserver`, `qcluster`.

This keeps the causal chain visible on the page: configure → docker compose reads `.env` → start Django.

### User

> go ahead

### Assistant

Applied the restructure to `README.md` and extended the plan, feature doc, and implementation session transcript to cover the new scope. Kept the existing commit and added a follow-up commit for the README change so the two concerns stay separable in history.

### User

> I just merged a PR into main. Can you pull the changes and verify your work against the main branch changes?

### Assistant

Fetched `origin/main`, which had advanced to `4cf2475` with the Embed-step + Qdrant service merge. Rebased the branch, resolving three conflicts: `CHANGELOG.md` ordering (Keep a Changelog: Added → Changed → Removed → Fixed), `README.md` Installation block (main had re-added a `docker compose up -d` line to Installation that the restructure had moved to "Running the services"), and clean auto-merges on `docker-compose.yml` and `.env.sample`.

Flagged two follow-up candidates:

1. Main's new Qdrant service in `docker-compose.yml` and its `RAGTIME_QDRANT_*` block in `.env.sample` repeated the old DB pattern (hard-coded ports, "defaults match docker-compose.yml" comment) — the same duplication we had just fixed for Postgres.
2. The README Configuration paragraph only mentioned Postgres vars flowing through, so if Qdrant got the same treatment, that paragraph would need to cover it too.

### User

> Implement points 1 and 2 above. Can we also rename the "db" service in the docker-compose file to "postgres" or "postgresql"? What's more used?

### Assistant

Checked existing usage: `.github/workflows/ci.yml` already uses `postgres`, the Docker Hub image is `postgres`, and the shorter name is more common in community compose files. Recommended `postgres`, applied the rename, parameterized the Qdrant HTTP port with `${RAGTIME_QDRANT_PORT:-6333}`, updated the `.env.sample` Qdrant section comment to match the DB pattern, expanded the README Configuration paragraph to list both Postgres and Qdrant vars, and updated two archival doc commands (`docker compose up -d qdrant db` → `qdrant postgres` in the Embed-step plan and feature docs) so the instructions still work after the rename. Extended the plan, feature, and session transcripts to cover the new scope, then committed on the worktree branch.
