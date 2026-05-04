# AGENTS.md

This file provides guidance to AI coding agents when working with code in this repository.

## Project

RAGtime is a Django app for ingesting jazz podcast episodes — fetching episode details, transcribing audio, extracting jazz entities, and powering **Scott**, a strict RAG chatbot that answers questions only from ingested content. The project overview lives in `README.md`; detailed pipeline, Scott, and Langfuse documentation lives in `doc/README.md`.

## Commands

```bash
uv sync                                    # Install/update Python dependencies
uv run python manage.py runserver --noreload  # Dev server (WSGI only — see note below)
uv run uvicorn ragtime.asgi:application --host 127.0.0.1 --port 8000  # ASGI, required for Scott
uv run python manage.py migrate            # Apply migrations
uv run python manage.py makemigrations     # Generate migrations
uv run python manage.py test               # Run all tests
uv run python manage.py test episodes      # Run tests for one app
uv run python manage.py configure          # Interactive setup wizard
uv run python manage.py configure --show   # Show current config (masked)
uv run python manage.py check              # Django system checks

# Frontend (Scott chat UI)
cd frontend && npm install                 # Install JS dependencies
cd frontend && npm run dev                 # Vite dev server (HMR) for chat UI
cd frontend && npm run build               # Production build into frontend/dist/
```

> **Scott needs ASGI.** Django's `manage.py runserver` runs in WSGI mode, which doesn't load `ragtime/asgi.py` — the path dispatcher that routes `/chat/agent/` to the Pydantic AI AG-UI app. Use `uvicorn ragtime.asgi:application` when working on Scott. `runserver` still works for everything else (admin, episodes, ingestion pipeline).

Use `uv` for Python; `npm` (or compatible) for the `frontend/` workspace. Never `pip install` directly.

## Architecture

**Three Django apps:**
- `core` — Project-wide management commands and utilities (e.g. `configure`)
- `episodes` — Ingestion pipeline, models, entity extraction, provider abstractions
- `chat` — Scott chatbot interface with streaming responses

**Provider abstraction:** LLM, transcription, and embedding backends are pluggable via abstract base classes in `episodes/providers/base.py` with a factory in `episodes/providers/factory.py`. Configured through `RAGTIME_*` environment variables.

**10-step pipeline** (steps defined in `episodes/models.py:PIPELINE_STEPS`, orchestrated by `episodes/workflows.py`): submit → fetch_details → download → transcribe → summarize → chunk → extract → resolve → embed → ready. There is also a transient `queued` state between submission and `fetching_details` that reflects "waiting for a worker slot in the `episode_pipeline` DBOS queue". Each step updates the episode status. Failures set status to `failed`. Runs as a DBOS durable workflow with PostgreSQL-backed checkpointing.

**Pipeline parallelism**: episodes are processed concurrently up to `RAGTIME_EPISODE_CONCURRENCY` (default 4) via the `episode_pipeline` DBOS queue. Beyond that limit, episodes sit in the `queued` state until a worker frees a slot — there is no fixed ceiling. Same-episode dedup is enforced via deterministic DBOS workflow IDs (`episode-<id>-run-<n>`) — DBOS rejects duplicate IDs, so a second enqueue on the same `(episode, run)` pair is a no-op rather than an error. DBOS owns workflow state (one `@DBOS.step()` per pipeline phase); `Episode.status` + `Episode.error_message` carry the user-facing summary.

> **Keep in sync:** When adding, removing, or changing a pipeline step, update the summary table in `README.md` and the detailed step descriptions in `doc/README.md`. If the change affects a diagram (e.g., Excalidraw files in `doc/`), flag it explicitly — diagrams cannot be auto-updated and may be out of sync after the change.

**Entity resolution (foreground):** After extraction, the resolver in `episodes/resolver.py` aggregates entity mentions per type, queries the local **MusicBrainz** Postgres database (`episodes/musicbrainz.py`, sub-millisecond, parallel-safe) for candidate MBIDs, and asks the resolution LLM to pick the best MBID + match against existing `Entity` rows. Race-safe: every create goes through `get_or_create` plus a sorted Postgres `pg_advisory_xact_lock` per `(entity_type, name)`. The foreground never calls Wikidata — `Entity.musicbrainz_id` is set directly when an MBID is resolved.

**Wikidata enrichment (background):** A singleton DBOS workflow on the `wikidata_enrichment` queue (`concurrency=1`) backfills `Entity.wikidata_id`. It tries the local `MBID → Wikidata` link in MusicBrainz first, then falls back to the rate-limited Wikidata API (`episodes/wikidata.py`). Per entity, deduplicated globally — common names get enriched once across all episodes. Status moves through `pending` → `resolved` (success) or `not_found` (after `MAX_ATTEMPTS` exhausted). `manage.py enrich_entities` backfills any entity still in `pending` status. Wikidata IDs flow into Scott's search results via search-time hydration in `episodes/vector_store.py` (Postgres join through `EntityMention → Entity`) — no Qdrant payload mutation.

**Slim Qdrant payload:** Qdrant chunk points carry only `chunk_id`, `episode_id`, `language`, `entity_ids` (server-side filter fields). Episode title, urls, chunk text, entity names, MBIDs, Wikidata IDs are hydrated from Postgres at search time via a single keyed query in `vector_store.search_chunks()`. Single source of truth — title edits and Wikidata enrichment flow through immediately without re-embedding or `set_payload` calls.

**MusicBrainz database setup:** Stand up a separate `musicbrainz` Postgres database alongside `ragtime` using [musicbrainz-database-setup](https://github.com/rafacm/musicbrainz-database-setup). Configure via `RAGTIME_MUSICBRAINZ_DB_HOST/_PORT/_NAME/_USER/_PASSWORD` and `RAGTIME_MUSICBRAINZ_SCHEMA` (defaults inherit from `RAGTIME_DB_*`, schema defaults to `musicbrainz`). The MB connection uses raw psycopg via `psycopg_pool.ConnectionPool` — bypasses the Django ORM since the MB schema is huge and read-only.

**Scott (RAG agent):** A Pydantic AI agent exposed as an AG-UI (HTTP+SSE) ASGI app mounted inside Django at `/chat/agent/`. The agent uses tool-call RAG: `search_chunks` embeds the user's question and retrieves top-k chunks from Qdrant; the system prompt mandates calling the tool before any factual answer and forbids general-knowledge fallbacks. Cites with `[N]` markers stable across multi-tool turns. Responds in the user's language via multilingual embeddings. Frontend is a React island built with assistant-ui + `@assistant-ui/react-ag-ui` via Vite + `django-vite`.

## Tech Choices

- Python 3.13 (`requires-python = ">=3.13,<3.14"`)
- No build-system in `pyproject.toml` (this is an app, not a library)
- PostgreSQL for relational data (via Docker Compose); Qdrant for vector store
- DBOS Transact for durable workflow execution (PostgreSQL-backed, no Redis needed)
- Pydantic AI for agent logic (fetch_details agent, download agent, Scott); AG-UI protocol for the chat streaming contract
- Frontend for the chat UI: React 19 + assistant-ui + Tailwind 4 via Vite + `django-vite`. Other pages stay server-rendered Django templates.
- `python-dotenv` for env vars (`.env` file, `RAGTIME_*` prefix)
- ffmpeg required for audio downsampling (files > 25MB)

## Branching

Before beginning any new work, always:
1. Verify we are on the `main` branch (`git branch --show-current`) and switch to it if not
2. Pull latest changes (`git pull --rebase`)
3. If there are any issues with steps 1–2 above, stop and ask for guidance before proceeding.

All new features and fixes must be implemented in a dedicated branch off `main`. Never commit directly to `main`. Use a descriptive branch name (e.g., `feature/transcribe-step`, `fix/dedup-race-condition`). Once the work is complete, open a pull request to merge back into `main`.

When creating PRs, use the rebase strategy. Squash and merge-commit strategies are not allowed on this repository.

## Documentation

### Planning phase

When a plan is accepted, save it to `doc/plans/`, one Markdown file per plan, with a `YYYY-MM-DD-` date prefix (e.g., `2026-03-15-my-feature.md`).

Save the planning session transcript to `doc/sessions/`, with a `YYYY-MM-DD-` date prefix and a filename ending in `-planning-session.md` (e.g., `2026-03-15-my-feature-planning-session.md`). Each transcript must include:

- **Session ID** — the actual Claude Code session UUID (e.g., `a150a5a3-218f-44b4-a02b-cf90912619d7`), after the `**Date:**` line. Do not use placeholders like "current session" or worktree names — retrieve the real UUID. Use `unavailable` only when the UUID cannot be recovered from session logs.
- **Summary** — a short `## Summary` describing what was planned.
- **Detailed conversation** — record the conversation as a sequence of `### User` and `### Assistant` sections. User messages must be verbatim, unedited text — copy the exact messages. Assistant sections may summarize tool calls, code changes, and internal reasoning into concise prose (since the raw output is tool invocations, not conversational text), but must capture what was done, what was explored, what alternatives were considered, and why a particular approach was chosen.

### Implementation phase

Feature documentation lives in `doc/features/`, one Markdown file per feature or significant change, with a `YYYY-MM-DD-` date prefix matching the plan file (e.g., `2026-03-15-my-feature.md`). Each document should include:

- **Problem** — what was wrong or what need the feature addresses.
- **Changes** — what was modified, with enough detail that a reader can understand the approach without reading the diff.
- **Key parameters** — any tunable constants, their values, and why those values were chosen.
- **Verification** — how to test the change on-device (deploy command + expected behaviour).
- **Files modified** — list of touched files with a one-line summary of each change.

Save the implementation session transcript to `doc/sessions/`, with a `YYYY-MM-DD-` date prefix and a filename ending in `-implementation-session.md` (e.g., `2026-03-15-my-feature-implementation-session.md`). Same format as the planning session (session ID, summary, verbatim conversation with reasoning steps). The implementation transcript must include all interactions up to and including PR review feedback and any follow-up changes made after the PR is created.

### Agent-orchestrated sessions

When a session is launched by a parent agent (e.g., a parallel implementation agent spawned from a parent Claude Code session in Conductor) and has no direct user-to-implementation-agent messages, the transcript must declare this honestly rather than fabricate `### User` content.

Use `### Parent agent (orchestrator)` headings *instead of* `### User` for such sections, and reproduce the parent-agent's launching prompt verbatim — same verbatim rule as for real user messages. This applies to either or both transcripts:

- **Planning transcripts** rarely fall into this case — planning sessions almost always have real user messages.
- **Implementation transcripts** frequently fall into this case under Conductor's parallel-launch workflow, where the user authorizes the parallel session in the parent conversation and the implementation agent runs from an agent-written brief.

Add a one-paragraph note at the top of the `## Detailed conversation` section explicitly identifying the session as agent-orchestrated and pointing at the parent conversation if accessible. Do not fabricate user messages, and do not silently summarize the parent prompt.

If the entire feature has no direct user messages anywhere (rare — usually the user at least authorized the work), the planning transcript may be omitted; the implementation transcript with the agent-orchestrated declaration is sufficient. Document the choice in the feature doc.

Every doc file must start with a `# Title` on the very first line. Metadata lines go immediately after the title, before any `## Section`: first `**Date:** YYYY-MM-DD` (all doc types), then `**Session ID:**` (session transcripts only). Never place metadata above the title. Separate each metadata line with a blank line so they render as distinct paragraphs in Markdown (e.g., a blank line between `**Date:**` and `**Session ID:**`).

Keep prose concise. Prefer tables and lists over long paragraphs. Use code blocks for CLI commands and signal-flow diagrams.

### Changelog & env vars

Whenever a `RAGTIME_*` environment variable is added, changed, or removed, update `.env.sample` and the configuration wizard (`core/management/commands/configure.py`) accordingly.

`CHANGELOG.md` follows the [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) format, using dates (`## YYYY-MM-DD`) as section headers instead of version numbers. Under each date, group entries by category (`### Added`, `### Changed`, `### Deprecated`, `### Removed`, `### Fixed`, `### Security`). Each entry includes a short description and links to the plan document, the feature document, and both session transcripts. Newest dates first; add to an existing date section if one already exists for today.

The commit for a given feature MUST contain the plan, the feature documentation, and both session transcripts (planning and implementation).

## PR Creation

When creating PRs, ensure the PR includes: plan document, feature doc, session transcripts (planning + implementation), and changelog entry. Review the Documentation section above for full requirements before creating the PR.

## GitHub API (`gh`)

When using `gh api` to interact with GitHub:

- **Shell escaping:** Always wrap request bodies containing backticks or special characters in a `$(cat <<'EOF' ... EOF)` heredoc. Bare backticks in `-f body="..."` will be interpreted by zsh as command substitution.
- **Replying to PR review comments:** POST to the pull's comments endpoint with `in_reply_to`:
  ```bash
  gh api repos/OWNER/REPO/pulls/PR_NUMBER/comments \
    -f body="reply text" \
    -F in_reply_to=COMMENT_ID
  ```
  There is no `/replies` sub-endpoint on individual comments — that returns 404.
- **Fetching PR review comments:** Use `gh api repos/OWNER/REPO/pulls/PR_NUMBER/comments` (not `/reviews`).
- **Fetching PR general comments:** Use `gh api repos/OWNER/REPO/issues/PR_NUMBER/comments` (PRs are issues).
