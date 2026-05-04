# Render non-applicable AI checks as gray "skipped"

**Date:** 2026-05-04

## Problem

`#122` shipped a self-hosted AI checks workflow that maps driver verdicts to GitHub job conclusions via exit code only. `skip` exited 0, identical to `pass`, so a non-applicable rule rendered as a green check — same icon as a rule that was checked and passed. No way for a reader of the PR Checks tab to tell the two cases apart.

GitHub Actions only renders the gray "skipped" icon for jobs whose `if:` condition evaluates false before the job starts. To fix the icon for path-scoped rules, the applicability decision has to move out of the runner and into the matrix-emitter `list` job.

## Changes

- **Matrix emitter** (`.github/scripts/list_ai_checks.py`). Now reads each rule's optional `paths:` frontmatter, runs `git diff --name-only $BASE_REF...HEAD` once, and emits an `applies: bool` field per matrix include. Rules without `paths:` always get `applies: true` (semantic — can't be path-decided). Top-level `BASE_REF` env var consumed.
- **Workflow** (`.github/workflows/ai-checks.yml`). The `list` job now does an `actions/checkout@v4` with `fetch-depth: 0` (needed to compute the diff), pre-fetches the base ref, and exports `BASE_REF` to the matrix emitter. The `check` job's `if:` condition gains `&& matrix.applies` — non-applicable shards render gray-skipped at the GHA level (no runner, no model call, no token cost).
- **Path-scoped rules.** Four rules now carry `paths:` frontmatter:
  - `pipeline-step-sync` → `episodes/models.py, episodes/workflows.py, README.md, doc/README.md, doc/*.excalidraw`
  - `asgi-wsgi-scott` → `ragtime/asgi.py, chat/**, frontend/**`
  - `qdrant-payload-slim` → `episodes/vector_store.py`
  - `entity-creation-race-safety` → `episodes/**`
  The other five rules (`branching-and-pr-strategy`, `comment-discipline`, `env-var-sync`, `feature-pr-docs`, `gh-api-shell-escaping`) stay unscoped because they're semantic — applicability requires reading the diff content, not just the file list.
- **Driver** (`.github/scripts/run_ai_check.py`):
  - System prompt: `skip` is removed from the verdict description. `pass` now covers both "complies" and "does not apply" — the latter with `summary: "Rule does not apply."` and a one-line `details` explanation.
  - Tool schema: `skip` removed from the `verdict` enum. The driver only ever returns `pass` or `fail`.
  - In-driver path-scoped early-return is preserved as a safety net for direct CLI invocation, but now returns `pass` with a "rule does not apply because no changed files match its path scope" note instead of `skip`.
  - Marker map updated; module docstring rewritten to reflect the new contract.

## Behaviour after the change

| Scenario | Old icon | New icon |
|---|---|---|
| Rule with `paths:` matches changed files, model returns `pass` | green | green |
| Rule with `paths:` matches changed files, model returns `fail` | red | red |
| Rule with `paths:` doesn't match any changed file | green (driver returned `skip`) | gray (job skipped at GHA level) |
| Rule without `paths:`, model returns `pass` | green | green |
| Rule without `paths:`, model returns `pass` with "does not apply" details | green | green (with explanatory details) |
| Rule without `paths:`, model returns `fail` | red | red |

On a PR that touches only `.github/` and `.ai-checks/` (like this one), the matrix emitter outputs:

```json
{"include": [
  {"name": "ASGI vs WSGI Awareness for Scott", "applies": false, ...},
  {"name": "Branching & PR Strategy", "applies": true, ...},
  {"name": "Comment Discipline", "applies": true, ...},
  {"name": "Entity Creation Race Safety", "applies": false, ...},
  {"name": "RAGTIME_* Env Var Sync", "applies": true, ...},
  {"name": "Feature PR Documentation Bundle", "applies": true, ...},
  {"name": "gh api Shell Escaping & Endpoints", "applies": true, ...},
  {"name": "Pipeline Step Documentation Sync", "applies": false, ...},
  {"name": "Slim Qdrant Payload Discipline", "applies": false, ...}
]}
```

Four shards skip to gray; five run as before.

## Key parameters

| Parameter | Value | Why |
|---|---|---|
| `paths:` glob syntax | Python `fnmatch` | Already what the driver used. `**` works because `*` matches `/`. |
| Default `applies` (no `paths:`) | `true` | Semantic rules can't be path-decided; better to evaluate than to silently skip. |
| `BASE_REF` default in `list` job | `origin/${{ github.event.pull_request.base.ref }}` | Same convention as the `check` job. |
| `fetch-depth` on `list` job | `0` | Required to compute `git diff` against base. |

## Verification

- `BASE_REF=main python .github/scripts/list_ai_checks.py` on this branch produces 4 `applies: false` and 5 `applies: true`. Matches issue acceptance criterion: "On a PR that touches none of `episodes/**`, `ragtime/asgi.py`, `chat/**`, `frontend/**`, at least 4 rules render as gray."
- `fnmatch.fnmatch` smoke-tested against `chat/sub/x.py vs chat/**`, `episodes/providers/base.py vs episodes/**`, `doc/foo.excalidraw vs doc/*.excalidraw` — all match.
- Project test suite (`uv run python manage.py test`) unaffected by these changes (touches only `.github/scripts/`, `.github/workflows/`, `.ai-checks/`).

## Files modified

- `.github/scripts/list_ai_checks.py` — emit `applies: bool` per matrix include from `paths:` frontmatter and `git diff --name-only`.
- `.github/scripts/run_ai_check.py` — drop `skip` from verdict enum and system prompt; rewrite path-scoped early-return and empty-diff branch to return `pass` with "does not apply" notes.
- `.github/workflows/ai-checks.yml` — add `fetch-depth: 0` and `BASE_REF` to `list` job; gate `check` matrix shards on `matrix.applies`.
- `.ai-checks/pipeline-step-sync.md` — add `paths:` frontmatter.
- `.ai-checks/asgi-wsgi-scott.md` — add `paths:` frontmatter.
- `.ai-checks/qdrant-payload-slim.md` — add `paths:` frontmatter.
- `.ai-checks/entity-creation-race-safety.md` — add `paths:` frontmatter.
