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
