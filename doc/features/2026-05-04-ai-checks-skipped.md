# Hide non-applicable AI checks from the PR Checks tab

**Date:** 2026-05-04

## Problem

`#122` shipped a self-hosted AI checks workflow that maps driver verdicts to GitHub job conclusions via exit code only. `skip` exited 0, identical to `pass`, so a non-applicable rule rendered as a green check — same icon as a rule that was checked and passed. No way for a reader of the PR Checks tab to tell the two cases apart.

The original goal was to render non-applicable rules as the gray "skipped" GitHub Actions icon, by emitting an `applies: bool` field per matrix shard and gating the job on `if: ${{ matrix.applies }}`. The codex review on PR #130 caught a blocker: GitHub Actions evaluates `jobs.<job_id>.if:` *before* expanding `strategy.matrix`, so `matrix.applies` is not available at that scope and the workflow fails to expand any jobs at all (0-second workflow-validation failure).

The smallest viable fix — and what this PR ships — is **filter non-applicable rules out of the matrix entirely** at emission time. Non-applicable rules simply don't appear in the PR Checks tab. That doesn't give us gray rows, but it does fix the original "indistinguishable from green pass" complaint, and it ships in a workflow YAML that actually runs. The future-work option (publishing gray rows via the GitHub Checks API from the `list` job) is tracked separately as #135.

## Changes

- **Matrix emitter** (`.github/scripts/list_ai_checks.py`). Now reads each rule's optional `paths:` frontmatter, runs `git diff --name-only $BASE_REF...HEAD` once, and **omits non-applicable rules from the emitted matrix entirely**. Rules without `paths:` always apply (semantic — can't be path-decided). The previously-emitted `applies` field is gone. `git diff` failures now fail closed (`sys.exit(1)`) instead of silently returning `[]`, so a bad base ref or fetch error causes the `list` job to fail loudly rather than silently dropping every path-scoped rule.
- **Workflow** (`.github/workflows/ai-checks.yml`). The `list` job does an `actions/checkout@v4` with `fetch-depth: 0` (needed to compute the diff), pre-fetches the base ref, and exports `BASE_REF` to the matrix emitter. The `check` job's `if:` is just `${{ fromJson(needs.list.outputs.matrix).include[0] != null }}` — guards the "no jobs to run" error when zero rules apply. No per-shard gate.
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

| Scenario | Old behavior | New behavior |
|---|---|---|
| Rule with `paths:` matches changed files, model returns `pass` | green check | green check |
| Rule with `paths:` matches changed files, model returns `fail` | red X | red X |
| Rule with `paths:` doesn't match any changed file | green check (driver returned `skip`) | rule absent from PR Checks tab |
| Rule without `paths:`, model returns `pass` | green check | green check |
| Rule without `paths:`, model returns `pass` with "does not apply" details | green check | green check (with explanatory details) |
| Rule without `paths:`, model returns `fail` | red X | red X |

On a PR that touches only `.github/` and `.ai-checks/` (like this one), the matrix emitter outputs only the five applicable rules:

```json
{"include": [
  {"name": "Branching & PR Strategy", "path": ".ai-checks/branching-and-pr-strategy.md"},
  {"name": "Comment Discipline", "path": ".ai-checks/comment-discipline.md"},
  {"name": "RAGTIME_* Env Var Sync", "path": ".ai-checks/env-var-sync.md"},
  {"name": "Feature PR Documentation Bundle", "path": ".ai-checks/feature-pr-docs.md"},
  {"name": "gh api Shell Escaping & Endpoints", "path": ".ai-checks/gh-api-shell-escaping.md"}
]}
```

The four path-scoped rules (`pipeline-step-sync`, `asgi-wsgi-scott`, `qdrant-payload-slim`, `entity-creation-race-safety`) are absent from the output entirely.

## Supported `paths:` syntax

The frontmatter parser is intentionally minimal — it is **not** a full YAML parser. The locked-in syntax for `paths:` is:

- **Single line.** Multi-line YAML lists (`paths:\n  - foo\n  - bar`) are not supported and are treated as an empty value (which means the rule incorrectly applies to every diff — don't write this form).
- **Comma-separated.** Split on `,`, with surrounding whitespace stripped from each pattern.
- **Unquoted.** Quote characters become part of the pattern. `paths: "foo"` will not match the file `foo`; write `paths: foo` instead.
- **Python `fnmatch` semantics**, not shell-segment-aware:
  - `*` matches any number of characters **including** `/`. So `doc/*.excalidraw` matches `doc/nested/foo.excalidraw`.
  - `**` is just two consecutive `*`; in practice `foo/**` matches `foo/bar/baz.py` because `*` already crosses `/`.
  - `?` matches exactly one character (also crossing `/`).
  - Character classes `[...]` are supported.

These constraints are documented in the docstrings of `parse_frontmatter` and `applies_for` in `.github/scripts/list_ai_checks.py` and locked in by unit tests in `.github/scripts/tests/test_list_ai_checks.py`.

## Key parameters

| Parameter | Value | Why |
|---|---|---|
| `paths:` glob syntax | Python `fnmatch` | Already what the driver used. `**` works because `*` matches `/`. |
| Default applicability (no `paths:`) | applies | Semantic rules can't be path-decided; better to evaluate than to silently skip. |
| `BASE_REF` default in `list` job | `origin/${{ github.event.pull_request.base.ref }}` | Same convention as the `check` job. |
| `fetch-depth` on `list` job | `0` | Required to compute `git diff` against base. |
| `git diff` failure behavior | `sys.exit(1)` | Fails the `list` job loudly. Silently returning `[]` would silently drop every path-scoped rule. |

## Verification

- `python -m unittest discover .github/scripts/tests -v` runs 24 unit tests covering `parse_frontmatter`, `applies_for`, `matches_paths`, `changed_files` (success + fail-closed paths), and `main()` end-to-end.
- `BASE_REF=origin/main python .github/scripts/list_ai_checks.py` on this branch emits exactly the 5 applicable rules (no `applies` field, no path-scoped entries).
- Project test suite (`uv run python manage.py test`) unaffected by these changes (touches only `.github/scripts/`, `.github/workflows/`, `.ai-checks/`).

## Future work

- **#135** — Publish gray "skipped" rows for non-applicable rules via the GitHub Checks API from the `list` job. This is the only way to render true gray-skipped icons given GHA's job-level `if:` evaluation order. Tracked as a separate issue because it needs a different shape (Checks API auth, conclusion publishing) than the matrix emitter.

## Files modified

- `.github/scripts/list_ai_checks.py` — filter non-applicable rules out of the matrix entirely; fail closed on `git diff` errors; document supported `paths:` syntax in docstrings.
- `.github/scripts/tests/__init__.py` — new test package marker.
- `.github/scripts/tests/test_list_ai_checks.py` — 24 new unit tests covering parser, glob matching, fail-closed diff behavior, and end-to-end matrix emission.
- `.github/scripts/run_ai_check.py` — drop `skip` from verdict enum and system prompt; rewrite path-scoped early-return and empty-diff branch to return `pass` with "does not apply" notes.
- `.github/workflows/ai-checks.yml` — `list` job has `fetch-depth: 0` and exports `BASE_REF`; `check` job's `if:` is just the `include[0] != null` empty-matrix guard (no per-shard `matrix.applies`, which doesn't work).
- `.ai-checks/pipeline-step-sync.md` — add `paths:` frontmatter.
- `.ai-checks/asgi-wsgi-scott.md` — add `paths:` frontmatter.
- `.ai-checks/qdrant-payload-slim.md` — add `paths:` frontmatter.
- `.ai-checks/entity-creation-race-safety.md` — add `paths:` frontmatter.
