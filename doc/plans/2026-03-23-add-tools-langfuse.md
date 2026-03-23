# Log Pydantic AI tool definitions to Langfuse

**Date:** 2026-03-23

## Problem

When viewing recovery agent traces in Langfuse, the `tools` array (JSON schemas describing each tool available to the model) is not visible in the input. Pydantic AI's built-in OTel instrumentation captures conversation flow and tool call invocations but does not include the tool definitions sent to the model.

## Approach

Log tool definitions manually as a Langfuse event inside the existing `_run_with_langfuse()` function. This is the least intrusive option compared to replacing Pydantic AI's internal OpenAI client with a Langfuse-wrapped one, which would risk double-tracing and Responses API compatibility issues.

## Steps

1. Add `_get_tool_definitions(agent)` helper that extracts tool name, description, and parameter JSON schema from the agent's `_function_toolset.tools`.
2. Add `_log_tool_definitions(agent, episode_id)` helper that creates a `recovery-tool-definitions` Langfuse event with the extracted schemas.
3. Call `_log_tool_definitions()` inside the `propagate_attributes` context in `_run_with_langfuse()`, before the agent run.
4. Add unit tests for both helpers.
5. Update changelog.
