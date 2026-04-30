---
name: RAGTIME_* Env Var Sync
description: New, renamed, or removed RAGTIME_* env vars must be reflected in .env.sample and the configure wizard.
---

# RAGTIME_* Env Var Sync

## Context

All runtime configuration uses the `RAGTIME_*` prefix and is loaded via
`python-dotenv` from a `.env` file. Two surfaces must stay in sync with the
code that reads these vars:

- `.env.sample` — the canonical "what can I configure?" reference checked
  into the repo
- `core/management/commands/configure.py` — the interactive setup wizard
  users run via `uv run python manage.py configure`

AGENTS.md is explicit: "Whenever a `RAGTIME_*` environment variable is
added, changed, or removed, update `.env.sample` and the configuration
wizard accordingly." Drift here breaks new-developer onboarding silently
— the app boots, but with the wrong defaults or with mysterious missing
features.

## What to Check

### 1. Newly-read env vars must appear in both surfaces

If the diff introduces a new `os.environ`, `os.getenv`, `env(...)`, or
`settings.RAGTIME_*` reference for a previously-unknown var, confirm:

- `.env.sample` has a line for the new var with a sensible placeholder
  and a brief comment explaining what it controls.
- `core/management/commands/configure.py` prompts for it (if user-facing)
  or has a clear reason it doesn't (e.g. internal-only, derived).

**BAD** — PR adds `RAGTIME_RESOLVER_LLM_TIMEOUT = int(os.getenv(...))` in
`episodes/resolver.py` but `.env.sample` and `configure.py` are unchanged.

**GOOD** — same code change, plus a `.env.sample` entry like
`# Timeout (seconds) for the resolver LLM call. Default: 30.` and a
matching prompt in `configure.py`.

### 2. Renames and removals must purge stale entries

If an env var is renamed (e.g. `RAGTIME_FOO` → `RAGTIME_BAR`) or removed,
both `.env.sample` and `configure.py` must drop the old name. Leaving the
old key around tells users to set a value that does nothing.

### 3. Default-value changes are user-visible

If the default for an existing var changes in code, the comment/example
in `.env.sample` should reflect the new default so users copying the
sample don't get surprising behaviour.

### 4. Secret-shaped vars must not leak example values

For API keys, tokens, and passwords, `.env.sample` should use a clearly
placeholder value (`your-anthropic-api-key`, `changeme`) — never a real
key, even a revoked one. Flag any commit that adds a value matching
`sk-`, `pk-`, `xoxb-`, or other obvious key prefixes.

## Key Files

- `.env.sample` — template
- `core/management/commands/configure.py` — interactive wizard
- `ragtime/settings.py` and any `episodes/`, `chat/`, `core/` module
  reading `RAGTIME_*` vars

## Exclusions

- Internal feature flags that are intentionally undocumented (rare;
  require a comment in code explaining why).
- Test-only env vars set in `tests/` and never read by production code.
