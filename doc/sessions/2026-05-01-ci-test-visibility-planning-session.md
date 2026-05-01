# CI Test Visibility — Planning Session

**Date:** 2026-05-01

**Session ID:** 75ddd764-8f66-42ff-a414-555f1ad38976

## Summary

Planned a scoped CI improvement to replace the wall-of-text test output on GitHub Actions with a structured, three-surface report (sticky PR comment, Check Run with diff annotations, workflow summary) by emitting JUnit XML from Django's existing test runner and publishing it via `EnricoMi/publish-unit-test-result-action`. The scope was deliberately decoupled from issue #115 (agent-evaluation framework) so that the eval-framework choice — pydantic-evals vs pytest+DeepEval — stays open. No pytest migration, no test-file renames, no folder restructuring, no CI matrix split. The full design tree was walked: reporter choice, action surfaces, comment mode, permissions scope, verbosity, check name, JUnit emitter, output path, output gating, test layout, and file naming convention. Each branch was resolved with an explicit decision.

## Detailed conversation

### User

Currently the unit tests results we see in GitHub are basically a wall of text. Let's dicuss how we could add better visibility to the tests results. This is work is in preparation of the agent evaluation framework we will be introducing when implementing issue #115.
Tasks:
- review the existing test suite
- could we structure the existing 330+ test suite into test groups for the different pipeline stages and chat (Scott) functionality

Questions:
- what would be the advantage of introducing pytest in regards to test implementation, test execution and test results reporting in the GitHub action test step
- would it help us to introduce something like this https://github.com/marketplace/actions/test-reporter

/grill-me

### Assistant

Explored the codebase before grilling: enumerated 358 test methods (later confirmed by user as 371) across 27 files in `core/tests/` and `episodes/tests/`. Read `ragtime/test_runner.py` and discovered the load-bearing `PostgresTestRunner` that terminates lingering async connections before `DROP DATABASE` — this constrains any runner replacement. Read `.github/workflows/ci.yml` and confirmed the suite is run via `uv run python manage.py test --verbosity 2` with no JUnit/XML output. Inspected GitHub issue #115 and observed that its body uses pytest examples (`@pytest.mark.deepeval`, `pytest.mark.parametrize`).

Opened with **Question 1**: should pytest be adopted everywhere (pytest-django) or only for the new eval suite, framing it as "issue #115 forces pytest into the repo." Recommended (A) full migration with the rationale that the visibility win and the eval-framework needs both want the same machinery.

### User

Regarding "Issue #115 forces pytest into the repo for the agent-eval framework", is this really decided? When implementing #115 we will explore options, including https://pydantic.dev/docs/ai/evals/evals/

### Assistant

Acknowledged the overstatement. Pydantic Evals is a real alternative — it can run standalone (`Dataset.evaluate()` returning a report) or inside a pytest harness — so #115 does not pre-commit to pytest. Restated the decision tree: the wall-of-text problem stands on its own and should not be entangled with #115.

Restated **Question 1** as "what is the *minimum* change that fixes the wall of text," with two paths: (A) stay on Django's runner and add JUnit XML via `unittest-xml-reporting`, (B) migrate to pytest-django for free `--junitxml`. Recommended (A) with the argument that the JUnit consumer (whichever GH action wins) does not care which runner produced the XML, so pytest migration could be argued separately later on its own merits.

### User

yes, let's go for A now. What are the decision points to choose either between dorny/test-reporter or EnricoMi/publish-unit-test-result-action?

### Assistant

Laid out a comparison table covering primary surface (Check Run vs sticky PR comment + Check Run + workflow summary), diff annotations, PR comment behavior, multi-suite handling, fork-PR support, format support, and maintenance. Distilled the decision to "where do you want to read the result — Checks tab vs PR conversation." Recommended EnricoMi for sticky-comment UX, single-suite fit, and JUnit-first focus. Flagged a third path: skip third-party actions and write the summary to `$GITHUB_STEP_SUMMARY` from a small script.

### User

What about https://github.com/marketplace/actions/test-reporter? Does it apply here?

### Assistant

Clarified that the marketplace listing `test-reporter` is the same `dorny/test-reporter` already covered. Re-anchored on whether it "applies here": yes, it consumes JUnit XML emitted by `unittest-xml-reporting` identically to EnricoMi. Noted that dorny gives a per-test Check Run tree but no PR comment, while EnricoMi gives both a comment and a Check Run.

### User

Ummm... tough choice. I like the idea of having a summary comment in the PR and also having it as a check. According to the GitHub action description page it seems to be possible to configure both: https://github.com/marketplace/actions/publish-test-results#publishing-test-results

### Assistant

Confirmed: EnricoMi publishes the Check Run, the sticky PR comment, and the workflow summary in a single action invocation, with each surface independently togglable via `comment_mode`, `check_run`, and `job_summary` inputs. Locked the reporter decision: **EnricoMi**.

Moved to **Question 3 (test grouping)**: single job vs matrix-by-stage vs Django parallel. Recommended single job, with the caveat that the answer depends on current CI duration, and asked the user to share that number.

### User

On CI/CD on GitHub, the "Run uv run python manage.py test --verbosity 2" step takes 52 seconds.

### Assistant

52s settled it — single job, no matrix, no parallel.

**Question 4 (JUnit emitter):** evaluated `unittest-xml-reporting` (de facto), `django-xmlrunner` (less popular wrapper), and rolling a custom XML emitter. Recommended `unittest-xml-reporting` with the integration approach of extending the existing `PostgresTestRunner` to emit XML when an env var (e.g. `JUNIT_XML_OUTPUT=1`) is set, so local runs stay clean. Bundled two sub-questions: env-var-gated vs always-on (recommended gated), and output path (recommended directory form `test-results/junit.xml`).

### User

yes

### Assistant

**Question 5 (EnricoMi config + CI workflow details, bundled):** five sub-decisions — comment mode, workflow permissions scope, verbosity level, check name, gitignore. Recommended `comment_mode: changes`, job-scoped `permissions: pull-requests: write, checks: write`, `--verbosity 1`, default check name (initially), and `.gitignore test-results/`.

### User

Agreed. Regarding (5d) what type of tests do we have now, unit tests or integration tests? OR a mixture? We currently have 371 tests.

### Assistant

Investigated by sampling test imports and counting `unittest.mock.patch` usage. Findings:

- All 27 files import from `unittest.mock` and use `patch` heavily — 139 occurrences in `test_resolve.py`, 88 in `test_transcribe.py`, 68 in `test_agent_tools.py`.
- All external calls (httpx, MusicBrainz psycopg pool, LLM providers, Qdrant) are mocked. No real LLM, no real MusicBrainz, no real Qdrant, no real audio.
- No `TransactionTestCase`, no `LiveServerTestCase`. Only `TestCase` (transaction-rollback) and `SimpleTestCase` (no DB at all in `test_musicbrainz.py`).
- The only real I/O in CI is the Django test DB (Postgres service container) — standard Django unit-test practice.

Concluded the suite is unambiguously unit tests by Django convention. No integration tests exist yet; the eval framework from #115 will be the first integration-shaped tests. Revised the check-name recommendation from "keep default" to **`"Unit Tests"`** — accurate today, disambiguates cleanly when #115's eval workflow lands.

### User

yes

### Assistant

Locked check name `"Unit Tests"`.

**Question 6 (test file restructuring):** flat layout vs subfolders by pipeline stage vs subfolders + carve-out for chat. Recommended keeping the flat layout because (a) filename prefixes already encode the pipeline stage, (b) EnricoMi/JUnit renders module hierarchy fine, (c) the pipeline-vs-chat split resolves itself via Django app boundaries (`chat/tests/` when those tests are added), (d) "pipeline vs cross-cutting" is a fuzzy boundary that invites bikeshedding, and (e) the move is reversible.

### User

I lean on agreeing with you on A. Nevertheless what I do not like about having "test_" as a **prefix** is that it adds a lot of noise when looking at the directory. I would rather prefer "test" to be a suffix. What are the best practices in Python? In the Java world we usually add "Test" at the end of the class name.

### Assistant

Honest answer: prefix `test_*.py` is the dominant Python convention by a wide margin, but suffix `*_test.py` is a recognized minority style with explicit tooling support. Hard facts:

- `unittest` stdlib defaults to `test*.py` (prefix only).
- Django `manage.py test` uses `DiscoverRunner.pattern = "test*.py"` by default — but it is configurable as a class attribute.
- pytest supports both `test_*.py` and `*_test.py` natively, documented.
- Coverage tools and IDE test runners follow whatever discovery pattern is set.

Cost to switch on this repo: rename ~27 files (git tracks renames cleanly), set `pattern = "*_test.py"` on `PostgresTestRunner` (one line — `DiscoverRunner` exposes it as a class attribute), update doc snippets in `CLAUDE.md`/`AGENTS.md`. Acknowledged the aesthetic argument: in a dedicated `tests/` directory (not mixed source+test), the prefix carries zero information and the domain word leads under the suffix convention. Recommended doing the rename as a separate PR after the visibility work, and ideally before #115 starts so eval test files are born with the right convention.

### User

Thanks for the clarification. Let's go with the standard Python approach and not rename the test files.

### Assistant

Locked: keep `test_*.py` prefix. Consolidated all resolved decisions into a summary table and listed the gotchas (the `if: always()` requirement on the EnricoMi step; push events not getting PR comments; the new Check being informational rather than an additional merge gate; the AGENTS.md docs deliverables; forward compatibility with #115). Offered two paths: keep grilling on under-explored branches or wrap up by writing the plan and session transcript.

### User

wrap-up

### Assistant

Confirmed the session ID via `~/.claude/projects/-Users-rafa-Develop-projects-ragtime/`, located the most recent `.jsonl` (`75ddd764-8f66-42ff-a414-555f1ad38976.jsonl`), and verified by reading `sessionId` from the log tail. Wrote the plan to `doc/plans/2026-05-01-ci-test-visibility.md` and this transcript to `doc/sessions/2026-05-01-ci-test-visibility-planning-session.md`. Did not create the feature branch or commit — per AGENTS.md, the plan + both session transcripts + the feature doc + the CHANGELOG entry land together in the implementation commit on the feature branch, not on `main`.
