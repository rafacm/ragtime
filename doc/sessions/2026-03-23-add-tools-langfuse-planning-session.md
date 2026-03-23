# Planning session: Log Pydantic AI tool definitions to Langfuse

**Date:** 2026-03-23

**Session ID:** 01TQ9vfjdH5MLG6Dy9ivRuAS

## Summary

Discussed why tool definitions are missing from Langfuse traces and chose the least intrusive approach to fix it.

### User

When looking in Langfuse for the requests sent to ChatGPT by Pydantic AI, I do not see the "tools" element in the input? Should I see it?

### Assistant

Investigated the codebase. The recovery agent uses Pydantic AI's built-in OTel instrumentation (`instrument=True`) which emits OpenTelemetry spans. These capture conversation flow and tool call results but not the `tools` definitions array (the JSON schemas). The pipeline steps use a different path — `langfuse.openai.OpenAI` — which wraps the raw HTTP client and does capture the full request payload including tools. Explained the two layers and confirmed this is expected behavior.

### User

Which one would be less intrusive with the existing code?

### Assistant

Compared two approaches: (1) patching `OpenAIProvider` to accept a Langfuse-wrapped client — risky due to Responses API vs Chat Completions mismatch and potential double-tracing, and (2) manually logging tool definitions as a Langfuse event — just a few lines in `_run_with_langfuse()`. Recommended option 2.

### User

yes

### Assistant

Proceeded to plan implementation: extract tool schemas from `agent._function_toolset.tools` via `Tool.function_schema.json_schema`, log them as a `recovery-tool-definitions` Langfuse event inside the existing `propagate_attributes` context.
