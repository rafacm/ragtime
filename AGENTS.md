# AGENTS.md

This file provides guidance to AI coding agents when working with code in this repository.

## Project

RAGtime is a Django app for ingesting jazz podcast episodes — scraping metadata, transcribing audio, extracting jazz entities, and powering **Scott**, a strict RAG chatbot that answers questions only from ingested content. The full specification lives in `README.md`.

## Commands

```bash
uv sync                                    # Install/update dependencies
uv run python manage.py runserver          # Run dev server
uv run python manage.py migrate            # Apply migrations
uv run python manage.py makemigrations     # Generate migrations
uv run python manage.py test               # Run all tests
uv run python manage.py test episodes      # Run tests for one app
uv run python manage.py check              # Django system checks
```

Use `uv` for everything — never `pip install` directly.

## Architecture

**Two Django apps:**
- `episodes` — Ingestion pipeline, models, entity extraction, provider abstractions
- `chat` — Scott chatbot interface with streaming responses

**Provider abstraction:** LLM, transcription, and embedding backends are pluggable via abstract base classes in `episodes/providers/base.py` with a factory in `episodes/providers/factory.py`. Configured through `RAGTIME_*` environment variables.

**12-step pipeline** (`episodes/pipeline.py`): submit → dedup → scrape → download → resize → transcribe → summarize → extract → resolve → chunk → embed → ready. Each step updates the episode status. Failures set status to `failed`. Runs async via Django Q2.

**Entity resolution:** After extraction, entities (artists, bands, albums, venues, sessions, labels, years) are resolved against existing DB records using LLM-based fuzzy matching to prevent duplicates.

**Scott (RAG agent):** Embeds user question → retrieves chunks from ChromaDB → LLM answers strictly from retrieved content with episode/timestamp references. Responds in the user's language via multilingual embeddings. No hallucination — refuses if no relevant content found.

## Tech Choices

- Python 3.13 (`requires-python = ">=3.13,<3.14"`)
- No build-system in `pyproject.toml` (this is an app, not a library)
- SQLite for relational data, ChromaDB for vector store
- Django Q2 with ORM broker (no Redis needed)
- Frontend: Django templates + HTMX + Tailwind CSS (CDN)
- `python-dotenv` for env vars (`.env` file, `RAGTIME_*` prefix)
- ffmpeg required for audio downsampling (files > 25MB)

## Branching

All new features and fixes must be implemented in a dedicated branch off `main`. Never commit directly to `main`. Use a descriptive branch name (e.g., `feature/transcribe-step`, `fix/dedup-race-condition`). Once the work is complete, open a pull request to merge back into `main`.

## Documentation

The detailed implementation plans for a given feature should be rendered as Markdown and saved to `doc/plans/`, one Markdown file per plan.

Feature documentation lives in `doc/features/`, one Markdown file per feature or significant change. Each document should include:

- **Problem** — what was wrong or what need the feature addresses.
- **Changes** — what was modified, with enough detail that a reader can understand the approach without reading the diff.
- **Key parameters** — any tunable constants, their values, and why those values were chosen.
- **Verification** — how to test the change on-device (deploy command + expected behaviour).
- **Files modified** — list of touched files with a one-line summary of each change.

Keep prose concise. Prefer tables and lists over long paragraphs. Use code blocks for CLI commands and signal-flow diagrams.

Add an entry for each feature or fix in the `Features & Fixes` section of `README.md` with the date the feature was implemented, a short description and a "Details" column with links to the plan document, the feature document and the session conversation.

The full conversation transcript for a given feature should be exported as a Markdown file and stored in `doc/sessions/`, one Markdown file per session.

The commit for a given feature MUST contain the corresponding Markdown files for the plan, the feature documentation and the session.
