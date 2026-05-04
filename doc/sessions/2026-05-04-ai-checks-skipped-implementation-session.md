# Implementation session: Render non-applicable AI checks as gray "skipped"

**Date:** 2026-05-04

**Session ID:** unavailable

## Summary

Implemented #124 in a single session. Enriched `list_ai_checks.py` to evaluate per-rule applicability against the PR's changed files, gated `check` matrix shards on `matrix.applies` in the workflow, populated `paths:` frontmatter on the four path-scoped rules per the issue's table, and removed `skip` from the driver's verdict enum and system prompt (folded into `pass` with a "rule does not apply" note). Verified the matrix emitter against this PR's own changed files and confirmed the expected 4-skipped / 5-applied split.

## Detailed conversation

### User

Detailed prompt from the parent agent: implement issue #124 end-to-end. Read AGENTS.md branching rules, run a staleness check on the existing AI checks scripts and rules, then do the four implementation steps from the issue (matrix-emitter applicability, workflow `if:` gate, rule frontmatter, prompt + tool tightening). Verify with the test suite and sample changed-file lists. Add a feature doc, plan, session transcripts, and changelog entry per CLAUDE.md "Documentation > Implementation phase".

### Assistant

**Step 0 — Branching.** Worktree was on `worktree-agent-abfd8394` at the same commit as `origin/main`. Created `rafacm/ai-checks-skipped` off main.

**Step 1 — Staleness check.** Read `run_ai_check.py`, `list_ai_checks.py`, the workflow YAML, and all 9 rule files. Findings:

- The driver (`run_ai_check.py`) already supports `paths:` frontmatter and short-circuits to `skip` when the file list doesn't match — but no rule file actually has `paths:` set yet.
- The matrix emitter (`list_ai_checks.py`) emits `{name, path}` per include, no `applies` field.
- The workflow has a top-level guard `fromJson(...).include[0] != null` to avoid empty-matrix errors but no per-shard `if: ${{ matrix.applies }}` gate.
- All 9 rule files have just `name:` and `description:` in their frontmatter.

Verdict: issue is unimplemented. Proceed.

**Step 2 — Implementation.**

1. **Rewrote `list_ai_checks.py`.** Added a `parse_frontmatter` helper that returns the full dict (not just `name`), a `changed_files` helper running `git diff --name-only $BASE_REF...HEAD`, and an `applies_for(fm, files)` predicate that matches the rule's `paths:` globs against the file list (`fnmatch.fnmatch`, any-vs-any). Rules without `paths:` get `applies: true`. Output schema becomes `{name, path, applies}`.

2. **Updated `.github/workflows/ai-checks.yml`.** Two changes:
   - The `list` job now does `actions/checkout@v4` with `fetch-depth: 0`, fetches the base ref, and exports `BASE_REF=origin/${{ github.event.pull_request.base.ref }}` to the matrix emitter step. Required so `git diff --name-only` works.
   - The `check` job's `if:` condition gains `&& matrix.applies` — non-applicable shards render gray-skipped at the GHA level. Added a comment explaining the semantics.

3. **Populated `paths:` frontmatter on 4 rules** per the issue's table:
   - `pipeline-step-sync.md` → `episodes/models.py, episodes/workflows.py, README.md, doc/README.md, doc/*.excalidraw`
   - `asgi-wsgi-scott.md` → `ragtime/asgi.py, chat/**, frontend/**`
   - `qdrant-payload-slim.md` → `episodes/vector_store.py`
   - `entity-creation-race-safety.md` → `episodes/**`

4. **Updated `run_ai_check.py`.** Removed `skip` from the verdict tool enum and from the system prompt. The system prompt now defines `pass` to cover both "complies" and "does not apply" cases — the latter with `summary: "Rule does not apply."` and an explanatory `details`. The empty-diff and path-scoped early-returns inside `evaluate()` were rewritten to return `pass` with a "rule does not apply because …" note instead of `skip`. Marker map (`{"pass": "PASS", "fail": "FAIL"}`) updated. Module docstring rewritten to reflect the new contract: "Path-scoped non-applicability is now handled at the workflow level."

**Step 3 — Verification.**

Ran `BASE_REF=main python .github/scripts/list_ai_checks.py` on the implementation branch. Output:

```
{"include": [
  {"name": "ASGI vs WSGI Awareness for Scott", ..., "applies": false},
  {"name": "Branching & PR Strategy", ..., "applies": true},
  {"name": "Comment Discipline", ..., "applies": true},
  {"name": "Entity Creation Race Safety", ..., "applies": false},
  {"name": "RAGTIME_* Env Var Sync", ..., "applies": true},
  {"name": "Feature PR Documentation Bundle", ..., "applies": true},
  {"name": "gh api Shell Escaping & Endpoints", ..., "applies": true},
  {"name": "Pipeline Step Documentation Sync", ..., "applies": false},
  {"name": "Slim Qdrant Payload Discipline", ..., "applies": false}
]}
```

4 path-scoped rules `applies: false`, 5 semantic rules `applies: true`. Matches the issue's acceptance criterion ("On a PR that touches none of `episodes/**`, `ragtime/asgi.py`, `chat/**`, `frontend/**`, at least 4 rules render gray").

Smoke-tested `fnmatch` semantics on `chat/sub/x.py vs chat/**`, `episodes/providers/base.py vs episodes/**`, `doc/foo.excalidraw vs doc/*.excalidraw`, `frontend/src/foo.tsx vs frontend/**` — all match. `**` works because Python's `fnmatch` lets `*` cross `/`.

Walked through the workflow YAML manually. The `list` job now needs `fetch-depth: 0` (added). The `check` job's `if:` condition `${{ fromJson(needs.list.outputs.matrix).include[0] != null && matrix.applies }}` is syntactically valid GHA expression syntax — `matrix.applies` is a per-shard context, the `include[0] != null` guard handles the empty-matrix case from before, and `&&` short-circuits correctly. No issues.

Ran `uv run python manage.py test --noinput`. 155 tests passed; 36 errors are environmental (missing `test_ragtime` Postgres database, MusicBrainz connection failures in the worktree env). None of the failures touch code paths modified by this PR — the changes live entirely in `.github/scripts/`, `.github/workflows/`, and `.ai-checks/`, which are not exercised by Django tests.

**Step 4 — Documentation.** Wrote `doc/plans/2026-05-04-ai-checks-skipped.md`, `doc/features/2026-05-04-ai-checks-skipped.md`, this implementation transcript, and the planning transcript. Added a `## 2026-05-04` section to `CHANGELOG.md` under `### Changed` linking to all four docs and citing #124.

**Step 5 — PR.** Pushed branch and opened PR per AGENTS.md.

## Revision after codex review

### User
> You are adding a follow-up commit to PR #130 in the rafacm/ragtime repo, addressing the blocking concern from the codex review. (...) The user has decided to ship **option 1B** (filter `applies: false` entries out of the matrix entirely) as the smallest viable fix. Option 1C (Checks API publishing) is captured separately as #135 for future work.

### Assistant

The codex review on PR #130 (review id `4218279237`) flagged the workflow design as blocking: `jobs.check.if: ${{ matrix.applies }}` does not work because GitHub Actions evaluates job-level `if:` *before* expanding `strategy.matrix`. The empirical signal was workflow run `25307264491` failing in 0 seconds with no jobs expanded.

Pivoted to **option 1B**:

1. `list_ai_checks.py` now omits non-applicable rules from the matrix entirely — no `applies` field on emitted entries. The `applies_for` helper is unchanged in semantics; `main()` simply `continue`s past rules where it returns `False`.
2. `ai-checks.yml` drops `&& matrix.applies` from the `check` job's `if:`, keeping only the `include[0] != null` empty-matrix guard. Updated the comment block to explain why per-shard gating doesn't work and to point at #135 as the future-work option.
3. `changed_files()` now fails closed: a `subprocess.CalledProcessError` triggers `sys.exit(1)` with a clear stderr message ("Refusing to silently skip path-scoped rules"), matching the codex review's "fail closed on a bad base ref" suggestion.
4. Added `.github/scripts/tests/__init__.py` and `.github/scripts/tests/test_list_ai_checks.py` — 24 stdlib-only `unittest` tests covering well-formed/missing/multi-line/quoted/comment frontmatter, empty/single/comma-separated/nonmatching/multi-matching `applies_for` cases, the codex-flagged `*`-crosses-`/` and `**`-not-segment-aware glob semantics, the new `sys.exit(1)` fail-closed path on `git diff` errors, and the end-to-end `main()` matrix-emission flow asserting only applicable rules appear and that no `applies` field is emitted. The quoted-glob and YAML-list-form unsupported behaviors are explicitly locked in by tests so a future "fix" doesn't silently change them.
5. Added docstrings on `parse_frontmatter` and `applies_for` documenting the supported `paths:` syntax (single-line, comma-separated, unquoted, `fnmatch` semantics — not segment-aware). Added a "Supported `paths:` syntax" section to the feature doc.
6. Updated the plan doc with a "Revision after codex review" section and updated the feature doc's design narrative to reflect the matrix-filter approach.

**Verification.** All 24 unit tests pass (`python -m unittest discover .github/scripts/tests -v`). Locally simulated matrix emission with `BASE_REF=origin/main python .github/scripts/list_ai_checks.py` — output contains only the 5 applicable rules with no `applies` field.

**Out of scope per the user's instructions.** Did not change verdict-enum work (already correct), did not change the four `paths:` frontmatter (already correct), did not tighten `entity-creation-race-safety` scope (deferred per codex), did not address the `## Plan...` first-line nit or the verbatim-user-messages nit on the original session transcripts (the user can address separately if they want).
