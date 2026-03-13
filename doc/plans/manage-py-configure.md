# `manage.py configure` — Plan

## Context

RAGtime uses 12 `RAGTIME_*` environment variables across 4 systems (scraping, summarization, extraction, transcription) to configure LLM and transcription providers. Manually editing the `.env` file is error-prone: typos in variable names go undetected, API keys are visible in plain text, and there is no guidance on which variables belong to which system or which can share credentials.

## Design

### Interactive CLI wizard

A Django management command (`python manage.py configure`) that walks the user through each system's settings interactively:

1. For each system (scraping, summarization, extraction, transcription), prompt for provider, API key, and model.
2. Scraping, summarization, and extraction all use LLM providers — offer to share provider and API key across them so users only enter credentials once.
3. Transcription is prompted separately (different provider type).
4. Write results to `.env` in the project root.

### `--show` flag

`python manage.py configure --show` prints the current configuration with API keys masked (e.g., `sk-abc...xyz`), without entering the interactive wizard.

### Safety

- Ctrl+C (KeyboardInterrupt / EOFError) exits cleanly at any prompt without corrupting the `.env` file.
- Existing `.env` values are preserved as defaults — the user can press Enter to keep them.

### Registry-based design

A `SYSTEMS` registry (list of dicts) defines each system's name, env var prefix, and available providers. Adding a new system means adding one entry to the registry — the wizard loop, env I/O, and display logic all derive from it automatically.

### New `core` Django app

The command lives in a new `core` app (`core/management/commands/configure.py`) for project-wide commands that do not belong to `episodes`. A companion `_configure_helpers.py` module contains the system registry, `.env` reading/writing, key masking, and prompt utilities.

## Changes

### 1. `core/` app (new)

- `core/__init__.py` — empty
- `core/apps.py` — `CoreConfig` with `default_auto_field` and `name`
- `core/management/__init__.py` — empty
- `core/management/commands/__init__.py` — empty
- `core/management/commands/_configure_helpers.py` — system registry, `read_env()`, `write_env()`, `mask_key()`, `prompt_choice()`, `prompt_secret()`, `prompt_text()`
- `core/management/commands/configure.py` — `Command` class with `--show` flag and interactive wizard loop
- `core/tests/__init__.py` — empty
- `core/tests/test_configure.py` — 23 unit tests covering helpers, `--show`, wizard flow, Ctrl+C handling, and shared credentials

### 2. `ragtime/settings.py`

- Add `'core'` to `INSTALLED_APPS`.

### 3. `README.md`

- Add Features & Fixes table entry for `manage.py configure`.

### 4. `AGENTS.md`

- Document the `core` app and `configure` command conventions.

## Files modified

| File | Action |
|------|--------|
| `core/__init__.py` | New — empty init |
| `core/apps.py` | New — Django app config |
| `core/management/__init__.py` | New — empty init |
| `core/management/commands/__init__.py` | New — empty init |
| `core/management/commands/_configure_helpers.py` | New — registry, env I/O, masking, prompt utilities |
| `core/management/commands/configure.py` | New — management command with `--show` and interactive wizard |
| `core/tests/__init__.py` | New — empty init |
| `core/tests/test_configure.py` | New — 23 unit tests |
| `ragtime/settings.py` | Edit — add `'core'` to `INSTALLED_APPS` |
| `README.md` | Edit — add features table entry |
| `AGENTS.md` | Edit — document `core` app conventions |
