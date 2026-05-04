## Plan: Render non-applicable AI checks as gray "skipped" instead of green "pass"

**Date:** 2026-05-04

## Problem

The AI checks workflow shipped in #122 maps driver verdicts to GitHub job conclusions via exit code only:

| Driver verdict | Exit code | GitHub icon |
|---|---|---|
| `pass` | 0 | green |
| `fail` | 1 | red |
| `skip` | 0 | green (should be gray) |

GitHub Actions has no exit code that maps to `skipped` — that conclusion only fires for jobs whose `if:` condition evaluated false *before* the job started. So `skip` verdicts currently render identically to `pass`, losing the distinction between "rule was checked and passed" and "rule didn't apply to the diff".

## Approach

Two coordinated changes.

### 1. Path-scope non-applicability in `list` job, gate matrix shards with job-level `if:`

Today `list_ai_checks.py` emits `{name, path}`. Enrich it to also evaluate per-rule applicability against the PR's changed files:

- Read each rule's `paths:` frontmatter (comma-separated `fnmatch` globs).
- Run `git diff --name-only $BASE_REF...HEAD` once.
- For each rule with `paths:`, set `applies: true` iff at least one changed file matches at least one glob. Rules without `paths:` always get `applies: true`.
- Emit `{name, path, applies}` per matrix include.

Then in `ai-checks.yml`, gate the `check` job on `matrix.applies` so non-applicable shards render gray-skipped at the GHA level — no runner spin-up, no model call, no tokens.

Populate `paths:` frontmatter on the four path-scoped rules per the issue's table:

| Rule | `paths:` |
|---|---|
| `pipeline-step-sync` | `episodes/models.py, episodes/workflows.py, README.md, doc/README.md, doc/*.excalidraw` |
| `asgi-wsgi-scott` | `ragtime/asgi.py, chat/**, frontend/**` |
| `qdrant-payload-slim` | `episodes/vector_store.py` |
| `entity-creation-race-safety` | `episodes/**` |

The other 5 rules stay unscoped (semantic; can't be path-decided).

### 2. Tighten the system prompt to remove `skip` for semantic non-applicability

After (1), the only remaining source of `skip` verdicts would be the model deciding "no relevant changes" for a semantic rule. Update the system prompt in `run_ai_check.py`:

- `pass`: diff complies with the rule, OR the rule does not apply. When non-applicable, set `summary` to "Rule does not apply." and put a one-line "rule does not apply because …" in `details`.
- `fail`: diff clearly violates the rule.
- ~~`skip`~~: removed from the verdict tool enum entirely.

Path-scoped non-applicability is now handled before the model is invoked — the early-return inside `evaluate()` is kept as a safety net for direct CLI invocation but now returns `pass` with an explanatory note.

## Acceptance criteria

- Rules with `paths:` frontmatter that no changed file matches render as gray "skipped" icon, no runner.
- Rules without `paths:` continue to evaluate semantically and render green/red.
- No green "skip" icons remain.
- On a PR that touches none of `episodes/**`, `ragtime/asgi.py`, `chat/**`, `frontend/**`, at least 4 rules render gray.
- On a PR that touches `episodes/vector_store.py`, `qdrant-payload-slim` fires (green or red), not gray.

## Out of scope

- Posting check-runs via the Checks API (gives full skipped-icon coverage including model-driven skips, but doubles the rows in the Checks tab unless we restructure away from `strategy.matrix`).
- Changing the rule format itself (frontmatter schema is unchanged — `paths:` was already supported by the driver, just unused).

## Revision after codex review (2026-05-04)

The codex review on PR #130 caught a blocker: GitHub Actions evaluates `jobs.<job_id>.if:` *before* expanding `strategy.matrix`, so a job-level `if: ${{ matrix.applies }}` gate is not visible at that scope and the workflow fails to expand any jobs at all (0-second workflow-validation failure).

Pivoted to **option 1B**: filter non-applicable rules out of the matrix entirely at emission time in `list_ai_checks.py`. Non-applicable rules simply don't appear in the PR Checks tab. This is not the gray-skipped icon the issue originally asked for, but it does fix the original "indistinguishable from green pass" complaint and ships in a workflow that actually runs.

Option 1C — publish gray rows via the GitHub Checks API from the `list` job — is the only way to render true gray-skipped icons given GHA's evaluation order. Tracked separately as **#135** for future work.

Other follow-ups landed in the same revision:

- `changed_files()` now fails closed (`sys.exit(1)`) on `git diff` errors instead of silently returning `[]`.
- New unit tests in `.github/scripts/tests/test_list_ai_checks.py` lock in parser, glob, and fail-closed behavior — including the explicitly-unsupported quoted-glob and YAML-list-form behaviors.
- `paths:` syntax is documented in docstrings on `parse_frontmatter` / `applies_for` and in the "Supported `paths:` syntax" section of the feature doc.
