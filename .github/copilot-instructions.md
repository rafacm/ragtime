# GitHub Copilot Code Review Instructions

This file provides custom instructions for GitHub Copilot when reviewing pull requests in the RAGtime repository.

## Project Context

RAGtime is a Django 5.2 app (Python 3.13) for ingesting jazz podcast episodes and powering **Scott**, a strict RAG chatbot. It has three Django apps: `core` (config/management), `episodes` (ingestion pipeline + entity extraction), and `chat` (Scott chatbot interface).

---

## Django Conventions

- **Always use `get_object_or_404`** in views that look up model instances by user-supplied identifiers.
- **Model `__str__`** must return a meaningful, human-readable string — not a PK or raw field dump.
- **`ForeignKey` `on_delete`** must be explicit and intentional (`CASCADE`, `PROTECT`, `SET_NULL`). Flag any `on_delete=CASCADE` on root-aggregate models as potentially destructive.
- **`null=True` on `CharField`/`TextField`** is not allowed — use `blank=True` with an empty-string default instead.
- **`unique_together` is deprecated** — use `UniqueConstraint` inside `Meta.constraints` instead.
- **All new models** need a migration generated with `uv run python manage.py makemigrations`.
- **Data migrations** that modify existing rows must be reversible (`forwards`/`backwards` functions).
- **Never call `save()` in a loop** — use `bulk_create` / `bulk_update` for batch writes.
- **URL patterns** must use named routes (`name=` parameter) so templates can use `{% url %}`.
- **Settings secrets** (`SECRET_KEY`, API keys) must never be hardcoded — they come from environment variables loaded via `python-dotenv`.

## Pipeline Architecture

- The ingestion pipeline flows through these statuses: `pending → scraping → needs_review → downloading → resizing → transcribing → summarizing → chunking → extracting → resolving → embedding → ready`. The constant `PIPELINE_STEPS` in `episodes/models.py` lists the 9 active processing steps (scraping through embedding); `PENDING`, `NEEDS_REVIEW`, `READY`, and `FAILED` are lifecycle states.
- Pipeline steps are dispatched as async Django Q2 tasks via `episodes/signals.py`. Each step lives in its own module (e.g. `episodes/scraper.py`, `episodes/chunker.py`). Do not call pipeline steps synchronously from views or other steps.
- Each step transitions `Episode.status` directly on the model instance. **Failures must set `status = FAILED`** and populate `episode.error_message` before re-raising.
- `NEEDS_REVIEW` is a manual gate after scraping — episodes pause here for human approval before downloading proceeds.
- New pipeline steps must be added to `PIPELINE_STEPS` in `episodes/models.py` and wired into `signals.py`.

## Entity Extraction & Resolution

- The **extract** step uses an LLM to identify jazz entities (artists, bands, albums, venues, recording sessions, labels, years) from episode chunks.
- The **resolve** step uses LLM-based fuzzy matching to merge extracted entities against existing DB records, preventing duplicates. Entity types have optional Wikidata Q-IDs (`EntityType.wikidata_id`) for external linking.
- Entity resolution logic lives in `episodes/resolver.py`. When modifying resolution, ensure deduplication correctness — a single entity mentioned under different names must resolve to one DB record.

## Provider Abstraction (`episodes/providers/`)

- All LLM, transcription, and embedding calls go through the **abstract base classes** in `episodes/providers/base.py`. Never call `openai` (or any external SDK) directly from pipeline steps — always use a provider instance obtained from the factory.
- New provider implementations must subclass the appropriate abstract base class and register in `episodes/providers/factory.py`.
- Provider selection is driven by `RAGTIME_*` environment variables. Any new configurable provider option needs a corresponding entry in `.env.sample` and `core/management/commands/configure.py`.

## Scott (RAG Chatbot)

- Scott answers questions **strictly from ingested content** — no hallucination. If no relevant chunks are found, Scott must refuse to answer rather than guess.
- Responses include episode and timestamp references so users can verify sources.
- Scott responds in the user's language via multilingual embeddings.

## Testing

- Tests use Django's `TestCase` (`from django.test import TestCase`), not `pytest`.
- Run tests with `uv run python manage.py test` — never use `pytest` directly.
- **Mock all external I/O**: HTTP calls, LLM/transcription provider calls, and `async_task` (Django Q2) must be patched with `@patch` or `unittest.mock.MagicMock`.
- Use `@override_settings` to inject test-specific `RAGTIME_*` environment values rather than modifying the real environment.
- Provider integrations should be tested with a stub/mock provider, not a real API call.
- Every new pipeline step module needs a corresponding `episodes/tests/test_<step>.py`.

## Security

- **`DEBUG = True` and a hardcoded `SECRET_KEY`** are acceptable only in development. Flag any PR that changes `ragtime/settings.py` to ensure secrets remain env-var-driven and `DEBUG` is not hard-coded to `True` in production paths.
- **Never log or expose raw API keys**, transcripts, or user-supplied URLs in error messages surfaced to the UI.
- **User-supplied URLs** submitted to the episode pipeline must be validated as HTTP/HTTPS before any network request is made.
- All `RAGTIME_*` env vars that hold secrets (API keys, tokens) must be masked when displayed (e.g., the `--show` flag of `configure`).

## Dependencies & Tooling

- **Use `uv` exclusively** — never `pip install`. Dependency changes go through `uv add` / `uv remove`, and `pyproject.toml` + `uv.lock` must be committed together.
- The project requires **Python 3.13** (`requires-python = ">=3.13,<3.14"`). Do not introduce syntax or APIs that require a different version.
- New runtime dependencies must use a major-version ceiling in `pyproject.toml` (e.g., `>=1.0,<2`), not open-ended pins.
- `ffmpeg` is a system dependency (not in `pyproject.toml`) — document any new system-level requirements in `README.md`.
