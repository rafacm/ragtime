# Session: PostgreSQL Docker Compose — Implementation

**Date:** 2026-03-23

**Session ID:** 168626d0-1f48-419b-9a7f-d17b2257f7b0

## Summary

Implemented the switch from SQLite to PostgreSQL with Docker Compose. Iteratively addressed CI workflow, Langfuse v3 compatibility issues, documentation updates, test database teardown problems, and Langfuse session ID uniqueness.

## Conversation

### User

(Plan approved via ExitPlanMode)

### Assistant

Implemented across 10 files: `docker-compose.yml` (PostgreSQL + Langfuse via profiles), `pyproject.toml` (psycopg), `settings.py` (postgresql backend), `.env.sample`, configure wizard, `dbreset` command, test fixtures, README updates. Fixed a test that relied on SQLite silently truncating a varchar value (`"Ignore previous instructions"` → `"INVALID"`). All 215 tests passed.

### User

How are unit tests going to be run now? Using PostgreSQL? How will this affect the CI/CD pipeline?

### Assistant

Added PostgreSQL 17 service container to `.github/workflows/ci.yml` with the same credentials as `docker-compose.yml`. Tests run against real PostgreSQL both locally and in CI.

### User

Is there something like TestContainers for Python that we could use for the tests?

### Assistant

Explained that testcontainers-python exists but doesn't add value here — Docker Compose is already required for dev, CI uses native service containers, and Testcontainers would add startup latency and a dependency for a problem that's already solved.

### User

Let's make sure we document the need for having PostgreSQL up and running in a new section in doc/README. Maybe we can call it "Development"?

### Assistant

Added Development section to `doc/README.md` with prerequisites, starting services, running tests, and resetting the database. Updated Langfuse setup to reference `docker compose --profile observability up -d`.

### User

Update the documentation to indicate in which localhost ports are Langfuse and PostgreSQL available

### Assistant

Added a service ports table: PostgreSQL on `localhost:5432` (always), Langfuse on `http://localhost:3000` and Langfuse DB on `localhost:5433` (observability profile). Noted all ports are `127.0.0.1` only.

### User

After starting "docker compose --profile observability up -d" I'm trying to access http://localhost:3000 and I get a ERR_CONNECTION_REFUSED

### Assistant

Discovered Langfuse v3 requires ClickHouse, Redis, MinIO, and two app containers — far more infrastructure than a simple compose profile.

### User

Ummm... on second thought let's leave Langfuse out of the Docker compose as it was before.

### Assistant

Removed all Langfuse services from docker-compose.yml, keeping PostgreSQL only. Reverted Langfuse setup docs to reference their self-hosting guide.

### User

It seems that the Langfuse docker compose configuration is also exposing the PostgreSQL port at 5432 and this clashes with our PostgreSQL instance.

### Assistant

Added a port conflict note to the Langfuse setup section with a `docker-compose.override.yml` workaround.

### User

Can one change the PostgreSQL port for Langfuse via the command-line?

### Assistant

Reviewed Langfuse's docker-compose.yml from GitHub. Port is hardcoded at line 162. Replaced the override.yml approach with a simpler sed command: `sed -i '' 's/127.0.0.1:5432:5432/127.0.0.1:5433:5432/' docker-compose.yml`. Internal Docker network connections are unaffected since `DATABASE_URL` uses the container hostname.

### User

Regarding "To reset the database (drops all data and recreates):" in the README, do we need to re-create the superadmin user afterwards?

### Assistant

Yes — added `createsuperuser` after `dbreset` in the README. The command already prints a reminder at the end.

### User

Do I need to explicitly create the ragtime database in PostgreSQL or will it be automatically created?

### Assistant

No — Docker's `POSTGRES_DB: ragtime` env var creates it automatically on first container start. Added a note to doc/README.

### User

With the SQLite implementation we had added delays in the code to prevent concurrent write access. Have we removed that code?

### Assistant

Searched the codebase — found no SQLite-specific delays or workarounds. The only SQLite config was the `timeout: 30` in DATABASES which was already removed.

### User

In Langfuse, for a given session id like "processing-run-1-episode-1" I am seeing old traces associated with it from days ago. Could it be that since I am resetting the database, the session id is the same but for different runs and this is the cause for this issue?

### Assistant

Confirmed: auto-increment PKs restart from 1 after database reset, producing duplicate session IDs. Discussed options: (1) add timestamp, (2) use UUIDs for PKs, (3) dbreset counter. User chose option 1 with `YYYY-MM-DD-HH-MM` format.

Added timestamps to both `processing-run-*` and `recovery-run-*` session IDs. Also fixed test database teardown — async threads from recovery agent tests left DB connections open, preventing PostgreSQL from dropping the test database. Created `PostgresTestRunner` that patches `_destroy_test_db` to terminate lingering connections before DROP.

All 243 tests pass with clean teardown.
