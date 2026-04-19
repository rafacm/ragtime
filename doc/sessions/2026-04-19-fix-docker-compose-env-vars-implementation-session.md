# Session: Fix docker-compose.yml to read DB credentials from .env — Implementation

**Date:** 2026-04-19

**Session ID:** 85c5300d-0f26-4d34-b9a9-02333c2f2312

## Summary

Replaced hard-coded PostgreSQL credentials in `docker-compose.yml` with Compose variable substitution backed by the existing `RAGTIME_DB_*` env vars, so `.env` becomes the single source of truth while a freshly cloned repo still runs with zero configuration. Updated the `.env.sample` DB section comment, added a `### Fixed` changelog entry, and committed the plan, feature doc, and both session transcripts on a dedicated worktree branch.

## Conversation

### Assistant

Entered the `fix/docker-compose-env-vars` worktree. Edited `docker-compose.yml` to use:

- `${RAGTIME_DB_PORT:-5432}:5432` for the published host port.
- `${RAGTIME_DB_NAME:-ragtime}`, `${RAGTIME_DB_USER:-ragtime}`, `${RAGTIME_DB_PASSWORD:-ragtime}` for `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`.
- `${RAGTIME_DB_USER:-ragtime}` for the `pg_isready -U` argument in the healthcheck — so a custom user also flows to the liveness probe.

No new env vars were introduced; all four substitution points reuse names already declared in `.env.sample`.

Validated with `docker compose config` twice:

1. No env set → `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` all resolve to `ragtime`, published port `5432`, healthcheck `pg_isready -U ragtime`. Defaults match the pre-change hard-coded values, so existing behaviour is preserved.
2. With `RAGTIME_DB_NAME=testdb RAGTIME_DB_USER=testuser RAGTIME_DB_PASSWORD=testpass RAGTIME_DB_PORT=5433` inlined → all four substitution points picked up the overrides, including the healthcheck (`pg_isready -U testuser`).

Updated `.env.sample` line 1 from `# Database (PostgreSQL) — defaults match docker-compose.yml` to `# Database (PostgreSQL) — docker-compose.yml reads these values (defaults: "ragtime" / port 5432)`, making the relationship explicit.

Wrote the four new documents under `doc/`:

- `doc/plans/2026-04-19-fix-docker-compose-env-vars.md`
- `doc/features/2026-04-19-fix-docker-compose-env-vars.md`
- `doc/sessions/2026-04-19-fix-docker-compose-env-vars-planning-session.md`
- `doc/sessions/2026-04-19-fix-docker-compose-env-vars-implementation-session.md` (this file)

Added a `### Fixed` entry to the existing `## 2026-04-19` section of `CHANGELOG.md`, cross-linking the plan, feature doc, and both session transcripts per the Keep a Changelog convention used throughout the file.

Staged all changes and committed on the worktree branch as `6e2d56c` ("Read PostgreSQL credentials in docker-compose.yml from .env").

### README restructure follow-up

User then asked to restructure the README's "Getting Started" section so Configuration appears before `docker compose up`, making it visible that `.env` values feed the database container. Noted that `manage.py configure` requires the code cloned and `uv sync` run first, so a literal "Configuration before Installation" ordering was impractical. Proposed and applied a three-subsection split:

1. **Installation** — `git clone` + `uv sync` only.
2. **Configuration** — wizard (`manage.py configure`) or manual `.env.sample` → `.env` copy. Added an explicit paragraph noting that `RAGTIME_DB_NAME`, `RAGTIME_DB_USER`, `RAGTIME_DB_PASSWORD`, and `RAGTIME_DB_PORT` are read by `docker-compose.yml`, with defaults (`ragtime` / port `5432`) when unset.
3. **Running the services** — `docker compose up -d`, `migrate`, `createsuperuser`, `load_entity_types`, `runserver`, `qcluster`. The `docker compose up -d` line carries an inline comment noting it reads `RAGTIME_DB_*` from `.env`. Kept the `dbreset` block intact.

Extended the plan and feature documents to cover the README restructure, and added this section to the implementation transcript. Committed the README change as a separate follow-up on the same worktree branch so the docker-compose fix and the README reorganization remain separable in history.

### Rebase onto main after Embed-step merge

User merged a PR into `main` that introduced the Embed pipeline step and added a Qdrant service to `docker-compose.yml`. Fetched `origin/main` and rebased the branch. Three conflicts:

1. `CHANGELOG.md` — main's `### Added` (Embed) and `### Removed` (Chroma vars) sat under the same `## 2026-04-19` date as the local `### Fixed`. Resolved by reordering to Keep a Changelog convention: Added, Changed (existing LangGraph entry), Removed, Fixed.
2. `README.md` — main added a `docker compose up -d` line to the Installation code block that the local restructure had moved out of Installation entirely. Resolved by dropping that line (already present in the new "Running the services" section) and updating the comment there to mention both services.
3. `docker-compose.yml` and `.env.sample` — auto-merged cleanly; local db-service substitutions sit alongside main's new Qdrant service and env vars.

Verified `docker compose config` still resolves correctly with and without env overrides, and `uv run python manage.py test` passes 281 tests (up from 261, +20 from the new Embed-step tests).

### Qdrant + service rename follow-up

User then asked for two follow-ups: apply the same env-var substitution treatment to Qdrant, and rename the `db` service to `postgres`/`postgresql`. Checked existing usage:

- `.github/workflows/ci.yml` already uses `postgres` as the service name.
- The Docker Hub image is `postgres`.
- Django's `DATABASES[...]['ENGINE']` uses `django.db.backends.postgresql`, but that's unrelated to the compose service name.

Went with `postgres` — shorter, matches the image and the CI service.

Applied:

- `docker-compose.yml` — renamed `db` → `postgres`; parameterized the Qdrant HTTP port via `${RAGTIME_QDRANT_PORT:-6333}`. Left the gRPC port `6334` hard-coded since no matching env var exists in `.env.sample`.
- `.env.sample` — updated the Qdrant section header comment to match the new DB pattern (from "defaults match docker-compose.yml" to "docker-compose.yml reads `RAGTIME_QDRANT_PORT`").
- `README.md` — expanded the Configuration paragraph into a bullet list covering both Postgres vars and `RAGTIME_QDRANT_PORT` with their defaults. Updated the `docker compose up -d` inline comment to mention both services read their config from `.env`.
- `doc/features/2026-04-19-embed-step.md` and `doc/plans/2026-04-19-embed-step.md` — updated the `docker compose up -d qdrant db` verification command to `postgres qdrant` so the instructions still work after the rename.
- Extended the plan, feature doc, and this transcript to reflect the expanded scope.

Validated with `docker compose config` and the full test suite before committing.

This transcript will be updated if PR review feedback produces follow-up changes.
