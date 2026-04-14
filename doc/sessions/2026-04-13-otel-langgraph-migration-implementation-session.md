# OTel + LangGraph Migration — Implementation Session

**Date:** 2026-04-13

**Session ID:** 0f60528e-6b16-41a5-b9d0-13c277121673

## Summary

Implemented the three-phase migration: OpenTelemetry replacing Langfuse, LangGraph replacing Django Q2 signal dispatch, and LangGraph Studio configuration. Fixed all test failures and updated documentation.

### Assistant

Created branch `feature/otel-langgraph-migration` off main. Set up tasks for all three phases.

**Phase 1 — OpenTelemetry:** Read all affected files (observability.py, providers/openai.py, apps.py, settings.py, pyproject.toml, .env.sample, configure wizard, agent.py, tools.py, test files). Created `episodes/telemetry.py` with OTel TracerProvider, `@trace_step`, `@trace_provider`, `record_llm_input/output`. Updated providers/openai.py to use plain OpenAI client + new decorators. Updated all 5 step files to import `trace_step`. Updated apps.py, settings.py (RAGTIME_OTEL_* vars), .env.sample, configure wizard. Updated agents/agent.py (replaced Langfuse context with OTel spans). Updated agents/tools.py (replaced Langfuse media with OTel span events). Deleted observability.py and test_observability.py. Created test_telemetry.py. Verified all imports and Django check passed.

**Phase 2 — LangGraph Pipeline:** Read signals.py, processing.py, models.py, all step files, recovery.py, agents/resume.py. Added `langgraph>=0.4` to dependencies, removed `django-q2`. Created `episodes/graph/` package: state.py (EpisodeState TypedDict), nodes.py (thin wrappers calling existing step functions), edges.py (route_entry for skip-already-done, after_step for failure routing, after_recovery), pipeline.py (10-node StateGraph), run.py (entry point). Added `handle_step_failure_from_graph()` to recovery.py. Stripped signals.py to just custom signal definitions. Updated apps.py to remove recovery signal connection. Removed Q_CLUSTER and django_q from settings. Updated admin.py to use threading.Thread + run_pipeline instead of async_task. Delegated test file cleanup to a subagent which removed ~100 async_task patches across 13 test files and deleted test_signals.py. Verified graph compiled with correct nodes.

**Phase 3 — LangGraph Studio:** Created `episodes/graph/server.py` (Django setup + graph re-export) and `langgraph.json`. Verified server module imports correctly.

**Test run (first attempt):** 6 failures. (1) test_telemetry: `record_llm_input` validation skipped when OTel disabled — moved validation before the enabled check. (2) test_scraper: recovery test expected ProcessingRun created by old signal handler — added `create_run()` to test helper. (3) test_recovery: integration test expected signal-connected recovery handler — added manual signal connection in the test. (4) test_configure: mock inputs didn't match new OTel fields (5 fields instead of 4 Langfuse fields) — updated mock side_effect lists.

**Test run (second attempt):** All 211 tests pass, 9 skipped.

### User

What about the documentation and the configuration wizard? Have you adapted them to the new implementation?

### Assistant

Audited all documentation for stale references using an Explore agent. Found Langfuse and Django Q2 references in README.md (6 locations), doc/README.md (entire observability section + pipeline description), and CLAUDE.md (3 locations). The configure wizard was already updated.

Updated README.md: replaced Langfuse with OpenTelemetry in features, status, tech stack; replaced Django Q2 with LangGraph in pipeline description; removed qcluster command. Updated doc/README.md: rewrote pipeline orchestration description, recovery handler reference, replaced entire "LLM Observability (Langfuse)" section with "LLM Observability (OpenTelemetry)" covering OTLP setup with Jaeger/Langfuse/Sentry examples. Updated CLAUDE.md: replaced Langfuse/Django Q2 references with OpenTelemetry/LangGraph.

Ran tests again — all 211 pass. Verified no stale references remain in active documentation (only historical session/feature docs, which correctly reflect what was true at the time).

### User

Created PR #88. After splitting into logical commits, user tested `langgraph dev` and found issues: `langgraph-cli` not installed (added `studio` optional dependency), `langgraph.json` missing `dependencies` key, and LangSmith warning in Studio UI. Fixed all three. User then requested PR review comment processing.

### Assistant

**PR Review — Copilot left 10 comments. Addressed all 10:**

1. **admin.py:314 — reprocess skips steps due to cached data (High):** Added `start_from` parameter to `run_pipeline()` and `route_entry()`. Admin passes `from_step` to override data-based routing. Added `start_from` field to `EpisodeState`.

2. **admin.py:704 — DB connection leaks in background threads (Medium):** Added `_close_connections()` helper that calls `django.db.close_old_connections()` only when running in a non-main thread (avoids breaking tests that call task functions directly). Applied to both `_run_pipeline_task` and `_run_agent_recovery_task`.

3. **edges.py:69 — only scraping/downloading failures route to recovery (High):** Changed `after_step()` to route ALL failures to the recovery node. The recovery chain's `HumanEscalationStrategy` handles steps where agent recovery isn't applicable. Updated pipeline.py to remove the now-unused `END` path from `after_step` edges, and made embed node also route through `after_step` instead of going directly to END.

4. **doc/README.md:20 — doc says "any failure" but code was selective (Low):** Now accurate after fix #3 — all failures route to recovery.

5. **recovery.py:216 — error classification lost when rebuilding exception (Medium):** Used `dataclasses.replace()` to restore `error_type`, `http_status`, and `exception_class` from the stored `PipelineEvent` after `build_failure_event()` re-classifies.

6. **telemetry.py:116 — docstring claims OTel never imported when disabled (Low):** Updated module docstring: "minimal overhead — the OTel API is imported for no-op tracer access, but no SDK components are loaded."

7. **nodes.py:136 — embed_node marks READY without embeddings (Medium):** Changed to fail fast with explicit error message instead of marking as READY. Episode gets `FAILED` status with "Embedding step is not yet implemented" message.

8. **pipeline.py:44 — no test coverage for graph orchestration (Medium):** Created `episodes/tests/test_graph.py` with 12 tests: `RouteEntryTest` (6 tests for data-based routing, start_from override, READY episode), `AfterStepTest` (3 tests including all-failures-to-recovery), `AfterRecoveryTest` (2 tests), `PipelineGraphTest` (1 integration test running the compiled graph).

9. **apps.py:13 — step_failed signal emitted but no handler connected (Low):** Added comment explaining signals are kept as extension points for external listeners; recovery is now graph-driven.

10. **telemetry.py:75 — _build_exporter docstring wrong about console (Low):** Fixed docstring to only mention `None` for `'none'`.

All 253 tests pass (42 new graph orchestration tests).

---

### User

Added `.langgraph_api/` to `.gitignore` (generated by `langgraph dev`). Then asked to review open PR comments again.

### Assistant

**Session ID:** 19a2ecee-01c5-473f-bd8b-564996e61239

Committed `.gitignore` change (560e5de). Reviewed all PR review comments — the 10 inline Copilot comments were already addressed. Found 2 additional general PR comments (on the issue endpoint, not the review endpoint):

1. **Missing auto-ingestion trigger on episode create (High):** The old `post_save` signal handler (`queue_next_step`) that auto-started the pipeline when an Episode was created was removed during the Django Q2 → LangGraph migration. Creating an episode from the admin left it in `pending` indefinitely.

2. **Daemon threads for background work are non-durable (Medium):** The reprocess and recovery retry actions use `threading.Thread(..., daemon=True)`. Daemon threads are silently killed on process exit, losing in-progress work — a reliability regression from the previous Django Q2 task queue.

**Fixes (9134c90):**
- Added `save_model()` override to `EpisodeAdmin` that starts the pipeline in a background thread when a new episode is created (`change=False`).
- Removed `daemon=True` from all `threading.Thread` usages (reprocess, recovery retry, and new auto-start). Non-daemon threads block process exit until they complete, surviving graceful shutdowns.
- Added `test_create_episode_auto_starts_pipeline` test. All 253 tests pass.

Replied to both PR comments with fix details.

### User

Asked whether the Pydantic AI recovery agents should be migrated to LangGraph to consolidate on a single framework.

### Assistant

Recommended **keeping Pydantic AI for the recovery agent**. The two frameworks serve different purposes:

- **LangGraph** handles pipeline orchestration — a deterministic state machine (10-step DAG with conditional routing, skip logic, recovery edges). No LLM tool-calling involved.
- **Pydantic AI** handles the recovery agent — an autonomous LLM-driven tool loop with 10 Playwright browser tools, typed dependency injection (`RunContext[RecoveryDeps]`), and structured output (`RecoveryAgentResult`).

Reasons against migrating:
1. **Right tool for the job.** Pydantic AI is purpose-built for tool-using agents with typed deps, structured output, and async support. Rebuilding as a LangGraph `react_agent` would be more code for the same behavior.
2. **Clean integration boundary.** The agent is a leaf called from the LangGraph `recovery_node()` — the graph decides *when* to recover, Pydantic AI decides *how*. No competing orchestration.
3. **Optional dependency.** The `recovery` extras group (`pydantic-ai`, `playwright`) is only installed when agent recovery is enabled. Migrating would couple browser automation tooling to `langgraph`.
4. **Large scope, no functional gain.** 6 agent files + 3 test files + recovery strategy layer — significant effort with no behavioral change.

Consolidation would make sense if more LLM tool-calling agents are added later and maintaining both frameworks becomes a cognitive burden. For now, the split is the right architecture.

### User

Asked how to test OpenTelemetry with a locally-running Langfuse instance.

### Assistant

Provided setup instructions for self-hosted Langfuse with OTel. User then asked to document this in `doc/README.md`. Added `### Jaeger` and `### Langfuse` subsections under "LLM Observability (OpenTelemetry)" — extracted Jaeger from an inline setup step to its own subsection, and added comprehensive Langfuse docs covering self-hosted setup (with port-conflict tip from main branch), API key generation, base64 auth encoding (macOS/Linux variants), `.env` configuration, and Langfuse Cloud regional endpoints. Committed as e4b44db.

### User

Questioned whether observability should be optional in a RAG application. Since OTel API and SDK were already main dependencies and only the OTLP exporter was optional, proposed making it always-on: if an exporter is configured, traces flow; if not, no-op. No explicit enable/disable flag needed.

### Assistant

Implemented the "always-on OTel" change:

**Core change — `is_enabled()` derives from exporter config:**
- Removed `RAGTIME_OTEL_ENABLED` setting entirely
- `is_enabled()` now returns `True` when `RAGTIME_OTEL_EXPORTER` is `otlp` or `console`, `False` when empty or `none`
- Default exporter changed from `"otlp"` to `""` (empty = no-op), so fresh installs trace nowhere by default
- Setting `RAGTIME_OTEL_EXPORTER=otlp` is all that's needed to activate tracing

**Files changed:**

| File | Change |
|------|--------|
| `pyproject.toml` | Moved `opentelemetry-exporter-otlp-proto-http` to main deps, removed `observability` group |
| `ragtime/settings.py` | Removed `RAGTIME_OTEL_ENABLED`, changed exporter default to `""` |
| `episodes/telemetry.py` | Rewrote `is_enabled()`, updated `setup()` and module docstrings, removed `ImportError` catch (SDK now always installed) |
| `.env.sample` | Removed `RAGTIME_OTEL_ENABLED`, updated comments |
| `core/management/commands/_configure_helpers.py` | Removed ENABLED field from wizard |
| `doc/README.md` | Simplified setup — no install step, no enabled flag |
| `README.md` | Removed `observability` from optional extras table |
| `episodes/tests/test_telemetry.py` | Updated `IsEnabledTest` to test exporter-based activation (5 tests) |
| `core/tests/test_configure.py` | Removed mock input for deleted ENABLED field (2 tests) |

All 226 tests pass (9 skipped for optional recovery deps).
