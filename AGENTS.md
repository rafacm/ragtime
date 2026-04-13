# AGENTS.md

This file provides guidance to AI coding agents when working with code in this repository.

## Project

RAGtime is a Django app for ingesting jazz podcast episodes — scraping metadata, transcribing audio, extracting jazz entities, and powering **Scott**, a strict RAG chatbot that answers questions only from ingested content. The project overview lives in `README.md`; detailed pipeline, Scott, and observability documentation lives in `doc/README.md`.

## Commands

```bash
uv sync                                    # Install/update dependencies
uv run python manage.py runserver          # Run dev server
uv run python manage.py migrate            # Apply migrations
uv run python manage.py makemigrations     # Generate migrations
uv run python manage.py test               # Run all tests
uv run python manage.py test episodes      # Run tests for one app
uv run python manage.py configure          # Interactive setup wizard
uv run python manage.py configure --show   # Show current config (masked)
uv run python manage.py check              # Django system checks
```

Use `uv` for everything — never `pip install` directly.

## Architecture

**Three Django apps:**
- `core` — Project-wide management commands and utilities (e.g. `configure`)
- `episodes` — Ingestion pipeline, models, entity extraction, provider abstractions
- `chat` — Scott chatbot interface with streaming responses

**Provider abstraction:** LLM, transcription, and embedding backends are pluggable via abstract base classes in `episodes/providers/base.py` with a factory in `episodes/providers/factory.py`. Configured through `RAGTIME_*` environment variables.

**10-step pipeline** (steps defined in `episodes/models.py:PIPELINE_STEPS`, orchestrated by LangGraph in `episodes/graph/pipeline.py`): submit → scrape → download → transcribe → summarize → chunk → extract → resolve → embed → ready. Each step updates the episode status. The graph's conditional edges enable step skipping and recovery routing. Failures set status to `failed` and route to the recovery node.

> **Keep in sync:** When adding, removing, or changing a pipeline step, update the summary table in `README.md` and the detailed step descriptions in `doc/README.md`. If the change affects a diagram (e.g., Excalidraw files in `doc/`), flag it explicitly — diagrams cannot be auto-updated and may be out of sync after the change.

**Entity resolution:** After extraction, entities (artists, bands, albums, venues, sessions, labels, years) are resolved against existing DB records using LLM-based fuzzy matching to prevent duplicates.

**Scott (RAG agent):** Embeds user question → retrieves chunks from ChromaDB → LLM answers strictly from retrieved content with episode/timestamp references. Responds in the user's language via multilingual embeddings. No hallucination — refuses if no relevant content found.

## Tech Choices

- Python 3.13 (`requires-python = ">=3.13,<3.14"`)
- No build-system in `pyproject.toml` (this is an app, not a library)
- PostgreSQL for relational data (via Docker Compose), ChromaDB for vector store
- LangGraph for pipeline orchestration (state graph with conditional routing)
- OpenTelemetry for LLM observability (pluggable OTLP backends)
- Frontend: Django templates + HTMX + Tailwind CSS (CDN)
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
