# Session: `manage.py configure`

**Date:** 2026-03-13

## Sessions

- `9a0dcfdd-1c99-4928-ad51-695753dfb44d` — planning
- (current session) — implementation

## Summary

Designed and implemented an interactive `manage.py configure` command that walks users through setting up all 12 `RAGTIME_*` environment variables, with support for shared credentials across LLM-based systems, API key masking, and a `--show` flag. Created a new `core` Django app to house project-wide management commands.

## Conversation

### User (session 1)

Asked to design a `manage.py configure` command for interactively setting up the project's environment variables.

### Assistant (session 1)

Analyzed the existing `RAGTIME_*` env vars across `ragtime/settings.py` and the README. Produced a plan covering: interactive wizard flow, `--show` flag, shared credentials for scraping/summarization/extraction, Ctrl+C safety, registry-based design, and a new `core` app. Saved the plan to `doc/plans/2026-03-13-manage-py-configure.md`.

### User (session 2)

Asked to implement the plan.

### Assistant (session 2)

Created the `core` Django app with the following structure:

- `core/__init__.py`, `core/apps.py` — app boilerplate
- `core/management/commands/_configure_helpers.py` — `SYSTEMS` registry defining each system's name, env prefix, and provider choices; `read_env()` and `write_env()` for `.env` file I/O; `mask_key()` for API key masking; `prompt_choice()`, `prompt_secret()`, and `prompt_text()` for interactive input
- `core/management/commands/configure.py` — `Command` class with `--show` flag that prints masked config, and an interactive wizard that prompts for each system's provider/key/model with an option to share credentials across the three LLM-based systems
- `core/tests/test_configure.py` — 23 unit tests covering env reading/writing, key masking, prompt helpers, `--show` output, full wizard flow, shared credentials, and Ctrl+C handling

Updated `ragtime/settings.py` to add `'core'` to `INSTALLED_APPS`. Updated `README.md` with a Features & Fixes table entry. Updated `AGENTS.md` with `core` app conventions.

Ran `uv run python manage.py test core` — all 23 tests passed.

### User (session 2)

Asked to create documentation files (plan, feature doc, session transcript).

### Assistant (session 2)

Created `doc/plans/2026-03-13-manage-py-configure.md`, `doc/features/2026-03-13-manage-py-configure.md`, and `doc/sessions/2026-03-13-manage-py-configure.md`.
