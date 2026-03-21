# Session: manage.py configure — Implementation

**Date:** 2026-03-13

**Session ID:** 3cb9e358-6f56-4fae-9d4c-8bc5a933756a

## Summary

Implemented the `manage.py configure` interactive CLI wizard: walks users through all 12 RAGTIME_* environment variables with shared credential support, secret masking, safe `.env` file writing, and a `--show` flag for displaying current configuration.

## Conversation

### User

Implement the following plan:

# Plan: `manage.py configure` — Interactive Setup Wizard

## Context

RAGtime has 12 `RAGTIME_*` environment variables across 4 provider systems (scraping, summarization, extraction, transcription), with more coming (embeddings, ChromaDB). Manually editing `.env` is error-prone and requires knowing all variable names. A guided `configure` command provides a quicker path to a working setup, especially for new developers.

## Design

**Interactive CLI wizard** that prompts for each system's settings, reads/writes a `.env` file, and masks API keys throughout. The key UX insight: scraping, summarization, and extraction often share the same OpenAI API key, so the wizard asks once and reuses.

### Flow

```
$ uv run python manage.py configure

RAGtime Configuration
=====================
Current values shown in [brackets]. Press Enter to keep.

--- LLM (scraping, summarization, extraction) ---
Use a single provider and API key for all LLM systems? [Y/n]:
  Provider [openai]:
  API key [***7xQ2]: <hidden input>
  Scraping model [gpt-4.1-mini]:
  Summarization model [gpt-4.1-mini]:
  Extraction model [gpt-4.1-mini]:

--- Transcription ---
  Provider [openai]:
  API key (Enter to reuse LLM key) [***7xQ2]: <hidden input>
  Model [whisper-1]:

Configuration written to .env
```

### Scope

Only the 4 currently implemented systems: scraping, summarization, extraction, transcription. Embeddings and ChromaDB sections will be added when those features land. The registry data structure makes this a simple addition.

### Key decisions

- **Secret input**: `getpass.getpass()` — no echo to terminal, no logging
- **Re-run safe**: reads existing `.env`, shows current values as defaults, preserves non-RAGTIME lines and comments
- **Extensible**: systems defined as a data structure (registry); adding embeddings/ChromaDB = adding an entry
- **No API validation**: no test calls — suggest `manage.py check` instead
- **`--show` flag**: print current config with masked secrets, no modification
- **Ctrl+C safe**: catches `KeyboardInterrupt`, writes nothing on cancel

## Files to create

This is a project-wide feature, not episodes-specific. A new `core` Django app holds project-wide management commands and utilities.

| File | Purpose |
|------|---------|
| `core/__init__.py` | App package init |
| `core/apps.py` | Django AppConfig for `core` |
| `core/management/__init__.py` | Empty package init |
| `core/management/commands/__init__.py` | Empty package init |
| `core/management/commands/configure.py` | Command class with `handle()` |
| `core/management/commands/_configure_helpers.py` | Env I/O, masking, system registry |
| `core/tests/__init__.py` | Tests package init |
| `core/tests/test_configure.py` | Unit tests |

## Implementation

### 1. `_configure_helpers.py` — System registry + utilities

**System registry** — declarative config for all promptable systems:

```python
SYSTEMS = [
    {
        "name": "LLM",
        "description": "Scraping, summarization, and extraction",
        "shareable": True,
        "subsystems": [
            {"prefix": "RAGTIME_SCRAPING", "label": "Scraping", "fields": [
                ("PROVIDER", "openai", False), ("API_KEY", "", True), ("MODEL", "gpt-4.1-mini", False)]},
            {"prefix": "RAGTIME_SUMMARIZATION", "label": "Summarization", "fields": [
                ("PROVIDER", "openai", False), ("API_KEY", "", True), ("MODEL", "gpt-4.1-mini", False)]},
            {"prefix": "RAGTIME_EXTRACTION", "label": "Extraction", "fields": [
                ("PROVIDER", "openai", False), ("API_KEY", "", True), ("MODEL", "gpt-4.1-mini", False)]},
        ],
    },
    {
        "name": "Transcription",
        "description": "Audio transcription",
        "shareable": False,
        "subsystems": [
            {"prefix": "RAGTIME_TRANSCRIPTION", "label": "Transcription", "fields": [
                ("PROVIDER", "openai", False), ("API_KEY", "", True), ("MODEL", "whisper-1", False)]},
        ],
    },
]
```

**Utility functions:**

- `read_env(path) -> (dict, list[str])` — parse `.env` into key-value dict + raw lines (to preserve comments). Split on first `=` only. Strip surrounding quotes.
- `write_env(path, values, original_lines)` — update existing lines in-place, append new keys at the end. Preserve comments and non-RAGTIME lines.
- `mask_secret(value) -> str` — `"***" + value[-4:]` if len ≥ 4, else `"***"` (empty → empty).
- `prompt_value(label, current, is_secret) -> str` — display with masked/plain default, use `getpass` for secrets. Enter = keep current.

### 2. `configure.py` — Command class

```python
class Command(BaseCommand):
    help = "Interactive guided setup for RAGtime environment variables"

    def add_arguments(self, parser):
        parser.add_argument("--show", action="store_true",
                            help="Show current configuration and exit")

    def handle(self, *args, **options):
        env_path = settings.BASE_DIR / ".env"
        existing, lines = read_env(env_path)

        if options["show"]:
            self._show_config(existing)
            return

        try:
            new_values = self._run_wizard(existing)
        except KeyboardInterrupt:
            self.stdout.write("\nConfiguration cancelled. No changes written.")
            return

        merged = {**existing, **new_values}
        write_env(env_path, merged, lines)
        self.stdout.write(self.style.SUCCESS(f"\nConfiguration written to {env_path}"))
```

**`_run_wizard`**: iterates over `SYSTEMS`. For shareable systems, asks "Use a single provider and API key?" — if yes, prompts once for provider+key then per-subsystem for model only. Always asks for provider name (even in shared mode) to future-proof for non-OpenAI providers. Tracks the last-set API key to offer "reuse LLM key" for transcription.

**`_show_config`**: prints each `RAGTIME_*` var with masked secrets.

### 3. Tests (`episodes/tests/test_configure.py`)

- `read_env`: parses key=value, handles comments, quoting, values with `=`
- `write_env`: preserves comments, updates existing keys, appends new ones
- `mask_secret`: edge cases (empty, short, normal)
- Command with `--show`: mock existing `.env`, verify masked output
- Command interactive flow: mock `getpass.getpass` and `builtins.input`, verify `.env` output
- Ctrl+C: verify no file written
- Re-run: verify existing non-RAGTIME lines preserved

## Files to modify

| File | Change |
|------|--------|
| `ragtime/settings.py` | Add `'core'` to `INSTALLED_APPS` |
| `README.md` | Add `configure` to Getting Started section and Features & Fixes table |
| `AGENTS.md` | Add `uv run python manage.py configure` to Commands section |

## Verification

```bash
# Run tests
uv run python manage.py test core.tests.test_configure

# Manual test — fresh setup (no .env)
rm -f .env && uv run python manage.py configure

# Manual test — re-run (updates existing .env)
uv run python manage.py configure

# Manual test — show mode
uv run python manage.py configure --show

# Verify .env is correct
cat .env

# Verify secrets not in git
git status  # .env should not appear
```


If you need specific details from before exiting plan mode (like exact code snippets, error messages, or content you generated), read the full transcript at: /Users/rafa/.claude/projects/-Users-rafa-Develop-projects-ragtime/9a0dcfdd-1c99-4928-ad51-695753dfb44d.jsonl

### Assistant

Let me start by reading the key existing files to understand the current state.

Now let me check the existing episodes app structure for reference patterns, then implement everything.

Good. Now let me create all the files. I'll create them in parallel where possible.

Now the main implementation files:

Now the tests:

Now update `settings.py` to add `core` to `INSTALLED_APPS`:

Now run the tests:

All 23 tests pass. Now let me also run the full test suite to make sure nothing is broken:

All 91 tests pass. Now update README.md and AGENTS.md.

Now update AGENTS.md architecture section to mention the `core` app:

Now create the doc files. Let me create the plan, feature, and session docs.

The core implementation is complete — all 23 tests pass and the full suite (91 tests) is green. I'm waiting on the background agent to finish creating the three doc files (plan, feature, session transcript). I'll let you know once it's done.

Here's what was created/modified:

**New files (core app):**
- `core/__init__.py`, `core/apps.py` — Django app boilerplate
- `core/management/commands/_configure_helpers.py` — System registry, `read_env`, `write_env`, `mask_secret`, `prompt_value`
- `core/management/commands/configure.py` — Command with `--show` flag and interactive wizard
- `core/tests/test_configure.py` — 23 unit tests

**Modified files:**
- `ragtime/settings.py` — Added `'core'` to `INSTALLED_APPS`
- `README.md` — Added `configure` to Getting Started and Features & Fixes table
- `AGENTS.md` — Added `configure` commands and updated architecture to mention `core` app

### User

Create a PR

### Assistant

Let me check on the doc agent and get the current state.

We're on the `docs-rename-scraping-provider` branch which is for a different feature. I need to create a new branch from `main`. Let me also check if the doc files were created.

The doc agent hasn't finished yet. Let me check its output, and if it's still running I'll create the docs myself to unblock the PR.

The agent is still running and has created the plan doc. Let me wait for it to complete — it's actively writing the files.

All doc files are ready. Now let me create a new branch from `main`, commit everything, and create the PR.

The stashed changes were made on `docs-rename-scraping-provider` branch, but now I'm on main which doesn't have those changes. I need to create the new branch and re-apply all changes cleanly.

Now I need to re-apply all the changes since the stash was on the wrong branch. Let me pop the stash — it should apply cleanly since the doc files from the agent are already on disk.

All changes are here. Let me check the diff and commit.

Everything looks correct. Let me run the full test suite one more time on the new branch, then commit and push.

91 tests pass. Now commit, push, and create the PR.

PR created: https://github.com/rafacm/ragtime/pull/23

### User

<task-notification>
<task-id>a4a7515dbb76897d9</task-id>
<tool-use-id>toolu_016VJKdKVCnVRL7JtLNkgDyn</tool-use-id>
<output-file>/private/tmp/claude-501/-Users-rafa-Develop-projects-ragtime/2a59d61c-6874-4f8a-953b-4280ec859794/tasks/a4a7515dbb76897d9.output</output-file>
<status>completed</status>
<summary>Agent "Create doc files for configure" completed</summary>
<result>All three documentation files have been created:

1. **Plan** -- `/Users/rafa/Develop/projects/ragtime/doc/plans/manage-py-configure.md` -- Describes the design: interactive wizard, `--show` flag, shared credentials, Ctrl+C safety, registry-based extensibility, and the new `core` app.

2. **Feature doc** -- `/Users/rafa/Develop/projects/ragtime/doc/features/manage-py-configure.md` -- Follows the same format as `refactor-rename-scraping-provider.md` with Problem, Changes, Key parameters, Verification, and Files Modified sections.

3. **Session transcript** -- `/Users/rafa/Develop/projects/ragtime/doc/sessions/2026-03-13-manage-py-configure.md` -- Follows the same format as the rename session doc, covering both the planning session (`9a0dcfdd-1c99-4928-ad51-695753dfb44d`) and the current implementation session.</result>
<usage><total_tokens>15266</total_tokens><tool_uses>8</tool_uses><duration_ms>55654</duration_ms></usage>
</task-notification>
Full transcript available at: /private/tmp/claude-501/-Users-rafa-Develop-projects-ragtime/2a59d61c-6874-4f8a-953b-4280ec859794/tasks/a4a7515dbb76897d9.output

### Assistant

The background doc agent finished — its files were already included in the commit and PR. Everything is done.

### User

I tested locally and the issue I see with this approach is that the generated `.env` file contains the API keys. Isn't there a better approach where the API keys are never stored on disk. Or if they are stored on disk they are encrypted.

### Assistant

Good point. The standard approach for this is to use the **system keychain** — macOS Keychain, Linux Secret Service, Windows Credential Vault — via the `keyring` library. API keys are stored encrypted by the OS, never written to `.env`.

The flow would be:

1. `configure` stores API keys in the system keychain via `keyring.set_password("ragtime", "RAGTIME_SCRAPING_API_KEY", value)`
2. `settings.py` reads keys from keychain at startup, falling back to env vars for CI/Docker where no keychain exists
3. `.env` only contains non-secret values (providers, models)
4. `--show` reads from keychain and masks as before

Before I implement this — a few considerations:

- **`keyring`** is a well-maintained library (used by pip, twine, etc.) and supports macOS/Linux/Windows natively
- **CI/Docker fallback**: environments without a keychain would still use `RAGTIME_*_API_KEY` env vars directly, so nothing breaks
- **`keyring` adds a dependency** — but it's pure Python with no heavy native deps on macOS (uses Security framework via ctypes)

Does this approach work for you, or would you prefer something different (e.g., encrypted `.env` file with a master password)?

### User

Thanks for the info. Let's keep is at is now. Let's tackle this in the future if needed.

### Assistant

Sounds good. The PR is ready as-is: https://github.com/rafacm/ragtime/pull/23
