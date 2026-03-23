# Log Pydantic AI tool definitions to Langfuse

**Date:** 2026-03-23

## Problem

Pydantic AI's OTel instrumentation (`instrument=True`) captures conversation flow and individual tool calls, but does not include the `tools` array — the JSON schemas sent to the model describing available tools. This makes it difficult to audit what tools the model had access to during a recovery run.

## Changes

- **`episodes/agents/agent.py`** — Added two helpers:
  - `_get_tool_definitions(agent)`: Extracts tool name, description, and `parameters` JSON schema from `agent._function_toolset.tools`. Returns `[]` on any error.
  - `_log_tool_definitions(agent, episode_id)`: Creates a `recovery-tool-definitions` Langfuse event with `input={"tools": [...]}` and metadata (`episode_id`, `tool_count`). Silently swallows errors.
  - Modified `_run_with_langfuse()` to call `_log_tool_definitions()` inside the `propagate_attributes` context, before `agent.run()`.

- **`episodes/tests/test_agent_langfuse.py`** — New test file with 6 tests covering schema extraction (single tool, multiple tools, error handling) and Langfuse event creation (happy path, no tools, Langfuse errors).

## Key parameters

None — no new configuration. The feature activates automatically when `RAGTIME_LANGFUSE_ENABLED=True`.

## Verification

1. Trigger a recovery agent run (e.g. via a scraping failure on a protected episode).
2. Open the recovery trace in Langfuse.
3. Look for the `recovery-tool-definitions` event — it should contain the full JSON schema for all 11 tools.

## Files modified

| File | Change |
|------|--------|
| `episodes/agents/agent.py` | Add `_get_tool_definitions()`, `_log_tool_definitions()`, call from `_run_with_langfuse()` |
| `episodes/tests/test_agent_langfuse.py` | New: 6 unit tests for tool definition extraction and Langfuse logging |
| `CHANGELOG.md` | Add entry under 2026-03-23 |
