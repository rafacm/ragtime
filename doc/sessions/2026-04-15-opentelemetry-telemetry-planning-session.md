# OpenTelemetry Telemetry — Planning Session

**Date:** 2026-04-15

**Session ID:** d2be50c4-9a66-4faf-bb43-29fbe4b0733a

## Summary

Planned the migration from Langfuse-specific observability to OpenTelemetry as the primary telemetry source, with console, Jaeger, and Langfuse as optional collectors.

### User

Let's plan about introducing OpenTelemetry as the source of telemetry data with console, Jaeger and Langfuse as optional collectors.

### Assistant

Explored the codebase in parallel with two agents:
1. **Telemetry exploration** — mapped the complete Langfuse integration: `episodes/observability.py` (256 lines), 5 pipeline steps decorated with `@observe_step()`, provider-level `@observe_provider` decorators, recovery agent OTel context isolation, configuration wizard, env vars, and tests.
2. **Project structure exploration** — mapped provider abstraction layer, Django settings, all `RAGTIME_*` env vars, configure wizard structure, and existing documentation.

Also searched the web for Langfuse v4 OTel attribute conventions and verified `opentelemetry-instrumentation-openai` package availability (v0.57.0 available). Checked PR #88 (`feature/otel-langgraph-migration`) which already prototyped `episodes/telemetry.py` and made OTel a core dependency.

Initial plan proposed OTel as optional. User corrected: "Telemetry is not optional. What will be optional is to use Langfuse or Jaeger as collectors." Also requested renaming `observability.py` to `telemetry.py` and checking PR #88 for prior art.

Fetched PR #88's `telemetry.py` implementation (284 lines) and configuration changes. Key design differences from PR #88: we support multiple simultaneous collectors (not just one exporter), preserve Langfuse-specific features (session_id, screenshots), and skip LangGraph migration.

### User

Telemetry is not optional. What will be optional is to use Langfuse or Jaeger as collectors. Let's rename observability.py to telemetry.py. Make sure the documentation and the configuration wizard are updated accordingly. Check what already exists in #88 regarding these two points.

### Assistant

Revised the plan to make OpenTelemetry a core dependency with optional collectors. Key decisions:

- **OTel always on**: Core dependency in `pyproject.toml`, no `[observability]` optional extra
- **`RAGTIME_OTEL_COLLECTORS`**: Comma-separated list replaces `RAGTIME_LANGFUSE_ENABLED`
- **Multiple processors**: Each collector gets its own `SpanProcessor` on the shared `TracerProvider`
- **Langfuse via OTel**: `langfuse.get_client()` registers its `LangfuseSpanProcessor` after our `TracerProvider` is set
- **`OpenAIInstrumentor`**: Replaces `get_openai_client_class()` pattern
- **Langfuse-specific features**: `is_langfuse_enabled()` guard for binary media (screenshots), `propagate_attributes()` for session_id/user_id
- **Jaeger in docker-compose.yml**: Under `telemetry` profile
