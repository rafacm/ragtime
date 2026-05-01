# CI Test Visibility

**Date:** 2026-05-01

## Problem

The CI test step (`uv run python manage.py test --verbosity 2`) emits a wall of unstructured text into the GitHub Actions log. With 371 tests across 27 files there is no per-test pass/fail summary, no failure isolation on the PR, no timing breakdown, and no way to scan for "what broke" without reading the entire log. This is preparatory work for the agent-evaluation framework planned in #115, which will add a separate test category whose results need to be readable alongside the existing suite.

## Goals

- Replace the wall-of-text CI log with a structured, glanceable view of test results on every PR.
- Make this change non-disruptive: zero existing test rewrites, no migration of the test runner, no new conventions.
- Leave the eval-framework decision (#115) genuinely open: pydantic-evals vs pytest+DeepEval is decided on its own merits, not pre-empted by this work.

## Non-goals

- Migrating to pytest. The existing 371 tests stay on Django's `manage.py test` runner.
- Renaming test files (`test_*.py` prefix vs `*_test.py` suffix). Standard Python convention is kept.
- Restructuring `episodes/tests/` into subfolders. Filenames already encode the pipeline stage.
- Splitting CI into a per-stage matrix. The full suite runs in 52s; matrix is pure overhead at this scale.
- Coverage reports.
- Branch-protection / required-check changes.

## Approach

Emit JUnit XML from Django's existing test runner, then publish it via `EnricoMi/publish-unit-test-result-action`. The action delivers three surfaces from a single config: a sticky PR comment (when results change vs base), a Check Run with diff annotations, and a rich workflow-run summary.

The custom `PostgresTestRunner` (`ragtime/test_runner.py`) is load-bearing — it terminates lingering async connections before `DROP DATABASE`. It must be preserved. The XML emission is added on top by hooking into `DiscoverRunner`'s extension points; it is gated by an environment variable so local `manage.py test` invocations do not litter the working tree.

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Reporter action | `EnricoMi/publish-unit-test-result-action` | Single action publishes PR comment + Check Run + workflow summary. |
| Comment mode | `changes` | Comments only when results differ from base — quiet on no-op pushes, loud on regressions. |
| Workflow permissions | Job-scoped `pull-requests: write`, `checks: write` | Least privilege; only the test job needs write access. |
| Check name | `"Unit Tests"` | Accurate today (all 371 tests are unit tests with mocked external deps). Disambiguates cleanly when the eval framework from #115 lands as a separate Check. |
| CI structure | Single job, no matrix, no parallel | Suite runs in 52s; matrix would add Postgres-startup overhead 9–10x for no wall-clock win. |
| Test verbosity in CI | `--verbosity 1` (down from `--verbosity 2`) | XML carries the structured info; the log only needs to surface unexpected failures. |
| JUnit emitter | `unittest-xml-reporting` (dev dep) | De-facto standard, mature, well-trodden integration with `DiscoverRunner`. |
| Runner integration | Extend `PostgresTestRunner` to emit XML when `JUNIT_XML_OUTPUT=1` is set | Preserves async-connection cleanup; gated to avoid local clutter. |
| Output path | `test-results/junit.xml` | Directory form is future-proof if a second report ever lands. |
| `.gitignore` | Add `test-results/` | Belt-and-suspenders against accidental local commits. |
| Test file layout | Keep flat | File names already pipeline-aligned; JUnit hierarchy renders the grouping. |
| Test file naming | Keep `test_*.py` prefix | Standard Python convention; no rename. |

## Implementation steps

1. **Add dev dependency.** `uv add --dev unittest-xml-reporting`. Verify it lands in the appropriate group in `pyproject.toml` (matching the existing dev/optional pattern).
2. **Extend `ragtime/test_runner.py`.** When `JUNIT_XML_OUTPUT=1`, configure `PostgresTestRunner` (or the suite it runs) to emit JUnit XML to `test-results/junit.xml`. Preserve the existing `_destroy_test_db_with_terminate` patch — that logic is unrelated to result emission and must keep working. The integration point is `DiscoverRunner.test_runner` / `get_resultclass` (or override `run_suite` to swap in `xmlrunner.XMLTestRunner`). Local invocations without the env var must behave identically to today.
3. **Add `test-results/` to `.gitignore`.**
4. **Update `.github/workflows/ci.yml`:**
   - Add a job-scoped `permissions:` block with `pull-requests: write`, `checks: write`, `contents: read`.
   - Set `env: { JUNIT_XML_OUTPUT: "1" }` on the `test` step.
   - Drop `--verbosity 2` to `--verbosity 1`.
   - Add a follow-up step using `EnricoMi/publish-unit-test-result-action@v2` with `if: always()`, `check_name: "Unit Tests"`, `comment_mode: changes`, `files: test-results/junit.xml`.
5. **Verify locally.** `JUNIT_XML_OUTPUT=1 uv run python manage.py test` should produce `test-results/junit.xml`. Check with one passing run and one deliberately-failed test that the XML reflects both.
6. **Verify in CI.** Open the PR, confirm: (a) sticky comment appears with the table, (b) "Unit Tests" Check shows up in the Checks tab, (c) workflow summary page renders the rich table, (d) inline annotations appear on the diff for any failing test.

## Gotchas

- **`if: always()`** on the EnricoMi step is required — otherwise the report is skipped exactly when you need it (when tests fail).
- **Push events have no PR comment.** EnricoMi still publishes the Check Run + workflow summary; the comment surface simply has nowhere to attach. Leaving the workflow trigger on both `push` and `pull_request` is the right behavior.
- **The new "Unit Tests" Check is informational, not an additional merge gate.** The existing `test` job already fails the workflow on test failure, which is what branch protection should already be observing.

## Documentation deliverables (per AGENTS.md)

The implementation PR commit must include:

- This plan: `doc/plans/2026-05-01-ci-test-visibility.md`
- Planning session transcript: `doc/sessions/2026-05-01-ci-test-visibility-planning-session.md`
- Implementation session transcript: `doc/sessions/2026-05-01-ci-test-visibility-implementation-session.md`
- Feature doc: `doc/features/2026-05-01-ci-test-visibility.md`
- `CHANGELOG.md` entry under `## 2026-05-01` (`### Added` for the JUnit emission and reporter action; `### Changed` for the CI verbosity drop).

Branch name: `feature/ci-test-visibility`.

## Forward compatibility with #115

Nothing in this plan precludes pydantic-evals or pytest+DeepEval as the eval framework. Whichever wins, #115's workflow can write its own JUnit XML and reuse `EnricoMi/publish-unit-test-result-action` with a different `check_name` (e.g. `"Fetch Details Eval"`).
