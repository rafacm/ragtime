# Feature: `manage.py configure`

**Date:** 2026-03-13

## Problem

RAGtime requires 12 `RAGTIME_*` environment variables across 4 systems (scraping, summarization, extraction, transcription). Manually editing the `.env` file is error-prone — variable names can be mistyped without detection, API keys sit in plain text with no masking, and there is no guidance on which variables belong to which system. Three of the four systems (scraping, summarization, extraction) use LLM providers and can share the same credentials, but this is not obvious from the flat env var list.

## Changes

- **`core/` app (new)** — A new Django app for project-wide management commands that do not belong to `episodes`.
- **`core/management/commands/configure.py`** — The `Command` class adds a `--show` flag (prints current config with masked secrets) and an interactive wizard that walks through each system's provider, API key, and model. Scraping, summarization, and extraction can share credentials. Ctrl+C exits cleanly at any prompt.
- **`core/management/commands/_configure_helpers.py`** — Contains the `SYSTEMS` registry (list of dicts defining each system's name, env prefix, and provider choices), plus utilities: `read_env()`, `write_env()`, `mask_key()`, `prompt_choice()`, `prompt_secret()`, `prompt_text()`.
- **`core/tests/test_configure.py`** — 23 unit tests covering env I/O, key masking, prompt utilities, `--show` output, full wizard flow with shared credentials, and Ctrl+C safety.
- **`ragtime/settings.py`** — Added `'core'` to `INSTALLED_APPS`.
- **`README.md`** — Added Features & Fixes table entry with links to plan and session docs.
- **`AGENTS.md`** — Documented `core` app conventions.

## Key parameters

| Flag | Effect |
|------|--------|
| `--show` | Print current `RAGTIME_*` configuration with API keys masked; do not enter interactive mode |

## Verification

```bash
uv run python manage.py test core
```

All 23 tests pass.

## Files Modified

| File | Change |
|------|--------|
| `core/__init__.py` | New — empty init |
| `core/apps.py` | New — `CoreConfig` app config |
| `core/management/__init__.py` | New — empty init |
| `core/management/commands/__init__.py` | New — empty init |
| `core/management/commands/configure.py` | New — management command with `--show` and interactive wizard |
| `core/management/commands/_configure_helpers.py` | New — system registry, env I/O, key masking, prompt utilities |
| `core/tests/__init__.py` | New — empty init |
| `core/tests/test_configure.py` | New — 23 unit tests |
| `ragtime/settings.py` | Added `'core'` to `INSTALLED_APPS` |
| `README.md` | Added features table entry |
| `AGENTS.md` | Documented `core` app conventions |
