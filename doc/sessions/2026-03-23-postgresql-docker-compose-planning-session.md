# Session: PostgreSQL Docker Compose — Planning

**Date:** 2026-03-23

**Session ID:** 168626d0-1f48-419b-9a7f-d17b2257f7b0

## Summary

Planned the switch from SQLite to PostgreSQL with Docker Compose to fix concurrent write locking errors. Discussed options for local PostgreSQL (Docker Compose), database reset tooling, Langfuse integration, and SQLite fallback.

## Conversation

### User

I'm seeing this error "sqlite3.OperationalError: database is locked" in the logs. What is the root cause?

### Assistant

Explained the root cause: SQLite concurrent write contention from multiple Django Q2 workers. Two pipeline steps running in parallel both trying to write, and SQLite only allows one writer at a time. Proposed three fixes: increase timeout, enable WAL mode, or limit to 1 worker.

### User

What about switching to use PostgreSQL? What would this entail?

### Assistant

Outlined the migration: change `DATABASES` backend, add `psycopg[binary]`, update `.env.sample` and configure wizard, no model/migration changes needed (Django ORM abstracts the DB layer). Discussed trade-offs: gains concurrent writes and better performance, loses zero-config simplicity. Recommended PostgreSQL for a multi-worker Django app.

### User

Which options do we have to spin up a local PostgreSQL server? Docker? We already have to spin up the actual Django app and the Django Q2 processes. Can we use something like Docker Compose for this? If we introduce PostgreSQL, how can we make it easier for users to create the database or reset the data if they want?

### Assistant

Explored the codebase to understand the current setup. Designed a plan with: Docker Compose for PostgreSQL (and optionally Langfuse via profiles), `manage.py dbreset` command, `RAGTIME_DB_*` env vars with dev defaults matching Docker Compose, Database section in configure wizard.

### User

But Langfuse is optional, how can we optionally spin up a Langfuse instance with Docker compose?

### Assistant

Explained Docker Compose profiles: tag Langfuse services with `profiles: ["observability"]`, they only start with `docker compose --profile observability up -d`. Regular `docker compose up -d` starts only PostgreSQL.

### User

Selected PostgreSQL only (no SQLite fallback) and asked about port security.

### Assistant

Ports bound to `127.0.0.1` only, not exposed to network. Renamed `resetdb` to `dbreset` per user preference. Plan approved.
