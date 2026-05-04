# Planning session: Render non-applicable AI checks as gray "skipped"

**Date:** 2026-05-04

**Session ID:** unavailable

## Summary

Issue #124 was filed by the project owner as a follow-up to the AI checks workflow shipped in #122. The plan was authored in the issue body itself rather than in a separate planning session — the two-part proposal (path-scope at `list` job + tighten the system prompt) is fully fleshed out, including the table of which rules to scope and which to leave semantic. Implementation followed the issue text directly. No separate planning conversation took place; this transcript captures the equivalent reasoning.

## Detailed conversation

### User

Filed issue #124 with title "Render non-applicable AI checks as 'skipped' (gray icon), not 'success' (green)". Body included:

- Background table mapping driver verdicts → exit codes → GitHub icons, identifying that `skip` exits 0 and renders identically to `pass`.
- Two-part proposal: (1) path-scope non-applicability in the `list` job and gate matrix shards with job-level `if: ${{ matrix.applies }}`; (2) tighten the system prompt to remove `skip` for semantic non-applicability.
- Suggested `paths:` frontmatter for 4 of the 9 rules.
- Acceptance criteria.
- Out-of-scope notes (Checks API approach deferred until path-scoping has been measured).

### Assistant

Reviewed the proposal end-to-end. Key reasoning steps:

1. **Why job-level `if:` rather than step-level.** GHA's `skipped` conclusion only fires for jobs whose `if:` evaluates false before the job starts. Using step-level `if:` on each step keeps the job at "success" (all-skipped-but-passing) and renders green, which defeats the purpose. Job-level `if:` against `matrix.applies` is the correct gate.

2. **Where to compute applicability.** Two places it could go: (a) inside the runner before the model call (today), (b) inside the matrix emitter (`list` job). Only (b) lets GHA short-circuit the job at the matrix level. Cost: the `list` job needs an `actions/checkout@v4` with `fetch-depth: 0` and a base-ref fetch, which it didn't have before — small overhead, one job, one shallow fetch.

3. **Path glob choice.** Stick with `fnmatch` since the driver already uses it. `**` works because Python's `fnmatch.fnmatch` treats `*` as matching any character including `/`, so `chat/**` matches `chat/sub/x.py`. Smoke-tested before adopting.

4. **Which rules to scope.** Took the issue's table verbatim — author had already done the analysis. The 5 rules left unscoped (`comment-discipline`, `branching-and-pr-strategy`, `env-var-sync`, `feature-pr-docs`, `gh-api-shell-escaping`) all need diff-content inspection (grep for `RAGTIME_*`, grep for `gh api`, PR-shape semantic judgment) — applicability isn't reducible to a path filter.

5. **What to do about `skip` in the driver.** After the workflow handles path-scoped non-applicability, the only remaining source of `skip` is the model deciding "no relevant changes" for a semantic rule. Option A: keep `skip` in the verdict enum, accept that it'll keep rendering green-pass. Option B: remove `skip` from the enum entirely, fold semantic non-applicability into `pass` with an explanatory `details` field. Picked B because it makes the verdict semantics cleaner — `skip` would only mean "couldn't evaluate", which is rare enough that it doesn't need a slot in the API.

6. **Safety net for direct CLI invocation.** The driver's existing path-scoped early-return inside `evaluate()` becomes redundant once the workflow gates on `applies`, but worth keeping for direct `python run_ai_check.py` runs. Adapted to return `pass` with a "rule does not apply" note.

7. **Out of scope.** Checks API (option 2 in the original design discussion in #121) gives full skipped-icon coverage — including model-driven skips — but doubles the rows in the Checks tab unless the workflow restructures away from `strategy.matrix`. Defer until path-scoping is measured in practice.

Plan accepted as written in the issue. Proceeded to implementation.
