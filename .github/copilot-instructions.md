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

## Pipeline Architecture (`episodes/pipeline.py`)

- The ingestion pipeline is a **12-step flow**: `submit → dedup → scrape → download → resize → transcribe → summarize → chunk → extract → resolve → embed → ready`. The constant `PIPELINE_STEPS` in `episodes/models.py` lists the 9 active processing steps (scraping through embedding); `PENDING`, `NEEDS_REVIEW`, and `READY` are the surrounding lifecycle states.
- Each step must call `update_episode_status()` at start and on completion/failure, transitioning through the correct `Episode.Status` choices in order.
- **Failures must set `status = FAILED`** and populate `episode.error_message` before re-raising.
- Each step runs as an async Django Q2 task dispatched via signals in `episodes/signals.py`. Do not call pipeline steps synchronously from views or other steps.
- New pipeline steps must be added to `PIPELINE_STEPS` in `episodes/models.py` and wired into `signals.py`.

## Provider Abstraction (`episodes/providers/`)

- All LLM, transcription, and embedding calls go through the **abstract base classes** in `episodes/providers/base.py`. Never call `openai` (or any external SDK) directly from pipeline steps — always use a provider instance obtained from the factory.
- New provider implementations must subclass the appropriate abstract base class and register in `episodes/providers/factory.py`.
- Provider selection is driven by `RAGTIME_*` environment variables. Any new configurable provider option needs a corresponding entry in `.env.sample` and `core/management/commands/configure.py`.

## Testing

- Tests use Django's `TestCase` (`from django.test import TestCase`), not `pytest`.
- Run tests with `uv run python manage.py test` — never use `pytest` directly.
- **Mock all external I/O**: HTTP calls, LLM/transcription provider calls, and `async_task` (Django Q2) must be patched with `@patch` or `unittest.mock.MagicMock`.
- Use `@override_settings` to inject test-specific `RAGTIME_*` environment values rather than modifying the real environment.
- Provider integrations should be tested with a stub/mock provider, not a real API call.
- Every new pipeline step module needs a corresponding `episodes/tests/test_<step>.py`.
- Test file names must match the module they test (e.g., `test_chunk.py` for `chunker.py`).

## Security

- **`DEBUG = True` and a hardcoded `SECRET_KEY`** are acceptable only in development. Flag any PR that changes `ragtime/settings.py` to ensure secrets remain env-var-driven and `DEBUG` is not hard-coded to `True` in production paths.
- **Never log or expose raw API keys**, transcripts, or user-supplied URLs in error messages surfaced to the UI.
- **User-supplied URLs** submitted to the episode pipeline must be validated as HTTP/HTTPS before any network request is made.
- All `RAGTIME_*` env vars that hold secrets (API keys, tokens) must be masked when displayed (e.g., the `--show` flag of `configure`).

## Dependencies & Tooling

- **Use `uv` exclusively** — never `pip install`. Dependency changes go through `uv add` / `uv remove`, and `pyproject.toml` + `uv.lock` must be committed together.
- The project requires **Python 3.13** (`requires-python = ">=3.13,<3.14"`). Do not introduce syntax or APIs that require a different version.
- New runtime dependencies must have a pinned minor-version range in `pyproject.toml` (e.g., `>=1.0,<2`), not open-ended pins.
- `ffmpeg` is a system dependency (not in `pyproject.toml`) — document any new system-level requirements in `README.md`.

## Documentation Requirements

Every PR that introduces a new feature or significant change must include:

1. **Plan document** — `doc/plans/<feature-name>.md`
2. **Feature document** — `doc/features/<feature-name>.md` (problem, changes, key parameters, verification, files modified)
3. **Planning session transcript** — `doc/sessions/*-planning-session.md` (Session ID, Summary, User/Assistant conversation)
4. **Implementation session transcript** — `doc/sessions/*-implementation-session.md` (same format)
5. **`CHANGELOG.md` entry** — dated section (`## YYYY-MM-DD`), grouped by `### Added / Changed / Fixed / ...`

When a `RAGTIME_*` environment variable is added, changed, or removed, `.env.sample` and `core/management/commands/configure.py` must be updated in the same PR.

## Code Style

- Keep functions focused and short. Pipeline step functions should do one thing.
- Prefer explicit over implicit — avoid `*args/**kwargs` in signatures unless the function genuinely needs variadic arguments.
- Use f-strings for string formatting; avoid `%` formatting or `.format()`.
- No unused imports. Flag any `import` that is not referenced in the file.
- Type annotations are encouraged for public functions and provider interfaces; not required for private helpers or test utilities.
