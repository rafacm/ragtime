# CI Test Visibility

**Date:** 2026-05-01

## Problem

The GitHub Actions test step (`uv run python manage.py test --verbosity 2`) emitted a wall of unstructured text. With 371 tests across 27 files there was no per-test pass/fail summary, no failure isolation on the PR, no timing breakdown, and no way to scan for "what broke" without reading the entire log. Preparatory work for the agent-evaluation framework planned in #115, whose results need to be readable alongside the existing suite.

## Changes

- **Dev dependency.** Added `unittest-xml-reporting` to the `dev` group in `pyproject.toml`.
- **Test runner.** Extended `ragtime/test_runner.py:PostgresTestRunner` with `run_suite()`. When `JUNIT_XML_OUTPUT=1` is set, the suite runs through `xmlrunner.XMLTestRunner` writing a single combined JUnit XML to `test-results/junit.xml`. The existing `_destroy_test_db_with_terminate` patch (load-bearing for async-connection cleanup) is untouched. Local invocations without the env var behave identically to before.
- **`.gitignore`.** Added `test-results/` so locally-generated XML never lands in commits.
- **CI workflow.** `.github/workflows/ci.yml`:
  - Added job-scoped `permissions:` block (`contents: read`, `pull-requests: write`, `checks: write`).
  - Set `JUNIT_XML_OUTPUT=1` on the test step.
  - Dropped `--verbosity 2` to `--verbosity 1` (XML carries the structured detail; the log only needs to surface unexpected failures).
  - Added an `EnricoMi/publish-unit-test-result-action@v2` step with `if: always()`, `check_name: Unit Tests`, `comment_mode: changes`, `files: test-results/junit.xml`. One action invocation publishes three surfaces: sticky PR comment (when results change vs base), Check Run with diff annotations, workflow-run summary.

`xmlrunner` writes a single XML file (with `<testsuites>` root) when its `output` argument is a file-like object rather than a directory. The runner pops `resultclass` from the kwargs Django supplies because `XMLTestRunner` installs its own incompatible result class.

## Key parameters

| Parameter | Value | Why |
|---|---|---|
| `JUNIT_XML_OUTPUT` | `1` (CI only) | Opt-in so local `manage.py test` invocations don't litter `test-results/`. |
| `comment_mode` | `changes` | Sticky comment posts only when results differ from base — quiet on no-op pushes, loud on regressions. |
| `check_name` | `Unit Tests` | Accurate today (all 371 tests mock external deps). Disambiguates cleanly when #115's eval workflow lands as a separate Check. |
| `--verbosity` | `1` | Minimal log noise; XML carries the per-test detail. |
| Output path | `test-results/junit.xml` | Directory form is future-proof if a second report ever lands. |

## Verification

**Locally:**
```bash
JUNIT_XML_OUTPUT=1 uv run python manage.py test
```
Confirmed `test-results/junit.xml` is produced (~128 KB, 371 `<testcase>` elements across `<testsuite>` per test class). Run without the env var produces no `test-results/` directory.

**In CI:**
1. Open a PR against `main`.
2. Confirm the workflow run renders a per-test summary table on the run page.
3. Confirm a `Unit Tests` Check appears in the PR's Checks tab.
4. Confirm a sticky comment is posted when results differ from base.
5. To exercise diff annotations, deliberately fail one test in a follow-up commit and confirm an inline annotation appears on the diff.

## Files modified

- `pyproject.toml` — added `unittest-xml-reporting` to `[dependency-groups].dev`.
- `uv.lock` — locked `unittest-xml-reporting==4.0.0` and its `lxml` transitive.
- `ragtime/test_runner.py` — added `run_suite()` override gated by `JUNIT_XML_OUTPUT=1`.
- `.gitignore` — added `test-results/`.
- `.github/workflows/ci.yml` — permissions, env, verbosity drop, EnricoMi publish step.
