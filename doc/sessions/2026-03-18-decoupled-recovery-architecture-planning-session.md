# Session: Decoupled Recovery Architecture — Planning

**Date:** 2026-03-18
**Session ID:** d7842f79-ffa8-4b5c-aa5c-336122a4a70d

## Summary

Planned a decoupled recovery architecture for pipeline failures in steps 2 (scraping) and 3 (downloading). Evaluated agentic AI frameworks (recommended Pydantic AI), browser automation tools (recommended Playwright direct Python API), and Langfuse observability integration. Evolved from an initial "agent hardwired into pipeline" design to a three-layer architecture: pipeline emits rich events, a recovery layer walks an escalation chain (agent then human), and the agent is a pluggable strategy behind a feature flag. Key decisions included dropping retry strategies, keeping the existing Langfuse SDK (no OTel migration), adding both success and failure pipeline events with admin visibility, and removing the unused `NEEDS_REVIEW` status.

## Conversation

### User

Sometimes in Step 2 (Scraping) we fail to find the URL for the episode MP3 audio and sometimes we find it but the download is blocked by the website in Step 3. Let's analyze if this is a case where we could introduce agentic AI so that if those steps fail, we trigger an agent with the goal of obtaining the missing information and retrigering the pipeline from that step. Which agentic frameworks would be candidates for the implementation?

### Assistant

Let me explore the current scraping and download implementation to understand the failure modes.

Now let me get a Plan agent to analyze the agentic framework options given this architecture.

Now let me read a couple of critical files to validate the plan details before writing it up.

Now I have a thorough understanding of the codebase and the framework landscape. Let me write the plan.

Here's a summary of the analysis:

**Top recommendation: Pydantic AI** — model-agnostic, type-safe, lightweight, sync-compatible with Django Q2, and right-sized for two single-agent recovery flows.

**Runner-up: OpenAI Agents SDK** — zero new dependencies (reuses existing `openai` package), but locks you to OpenAI models.

**Key insight**: If the recovery strategies are deterministic ("try RSS, then headless browser, then give up"), you may not need a framework at all — a simple fallback chain would suffice. The agent approach pays off when the LLM needs to *reason* about which strategy to try based on the error and page content.

The plan also covers failure analysis, what the agents would do, and which frameworks to avoid (LangGraph, CrewAI, smolagents) with reasons.

Good question. There are a few browser automation options that work with Pydantic AI, and the headless vs. visible requirement is a key differentiator.

Great findings. Let me update the plan with the browser automation analysis.

Here's the summary on browser automation:

**Playwright (direct)** is the clear winner. Key reasons:

- **Headed/headless toggle** is trivial — `launch(headless=False)` lets you watch the agent work in real time, `True` for production. Controlled via a single env var.
- **Right separation of concerns** — Pydantic AI is the brain (decides strategy), Playwright provides the hands (navigate, click, extract, capture network). Each browser action is a clean, testable tool function.
- **No double-agent problem** — Browser Use and Stagehand both have their own LLM agent loops, which conflicts with Pydantic AI as orchestrator (double LLM calls, loss of control, cost multiplication).
- **Sync API** works natively in Django Q2 tasks. Lightweight dependency (one package + Chromium binary).

The alternatives (Browser Use, Stagehand, Selenium, Playwright MCP) all have significant drawbacks — either architectural conflicts, heavy dependencies, or Node.js requirements.

Good clarification — so headed mode is off the table (server-only), and the real requirement is **step-by-step screenshots with cursor position sent to Langfuse for observability**. That changes the evaluation. Let me research Langfuse integration and revisit Stagehand.

Excellent research. Let me update the plan and address your questions directly.

**Stagehand — not a good fit even with the open-source offering.** Here's why:

1. **Double LLM calls**: Even the simple `act("click download")` and `extract(schema)` methods make their own internal LLM calls. So every browser action costs 2 LLM invocations — Pydantic AI deciding what to do, then Stagehand's own LLM interpreting the instruction. This is expensive and opaque.
2. **No Langfuse integration**: You'd need to manually instrument Stagehand's internal LLM calls separately.
3. **No cursor in screenshots**: `auto_screenshot` exists but without cursor overlay.
4. **Python SDK is immature**: The TypeScript version is primary; the Python SDK is newer and less tested.
5. **The open-source version works locally** (no Browserbase cloud required), but it still needs an LLM API key for every `act`/`extract` call — it's not just browser automation, it's AI-browser automation with its own reasoning layer.

**The better approach: Custom Playwright wrapper + Langfuse.**

- **Pydantic AI has production-ready Langfuse integration** via OpenTelemetry — `Agent.instrument_all()` and every tool call, LLM call, and agent step becomes a Langfuse trace.
- **Screenshots with cursor**: Inject a small CSS overlay (~40 lines of JS) that renders a red dot at the cursor position. `page.screenshot()` captures it. Playwright itself doesn't render cursors in headless mode, but this solved pattern works reliably.
- **Attach screenshots to Langfuse**: Use `LangfuseMedia(content_bytes=png_bytes, content_type="image/png")` to attach each screenshot to the current span. You get a full visual trail in Langfuse: agent thought → tool call → screenshot → next thought.
- **Single agent loop**: Only Pydantic AI reasons. Playwright just executes deterministic actions. 1 LLM call per step, not 2.

Let me update the plan.

To answer your questions directly:

**Stagehand**: Even the open-source local mode has the double-LLM-call problem. Every `act("click download")` triggers Stagehand's own LLM to interpret the instruction — that's the core of what Stagehand does. You'd pay for 2 LLM calls per browser action (Pydantic AI + Stagehand), and Stagehand's internal calls are invisible to Langfuse. It also doesn't render cursor position in screenshots.

**Langfuse integration**: Pydantic AI has production-ready Langfuse support via OpenTelemetry. Screenshots attach to spans via `LangfuseMedia`. With a custom Playwright wrapper, every step gets: agent reasoning (traced) → tool call (traced) → screenshot with cursor (attached as image) → all visible in the Langfuse dashboard.

The plan now reflects the updated requirements — headless-only with Langfuse observability replacing the headed "spy" mode.

Neither MCP server nor CLI — **direct Python API integration**. Here's how it works:

### Playwright as Pydantic AI Tool Functions (direct Python)

Playwright has a native Python package with a **sync API** (`sync_playwright()`). Each browser action becomes a plain Python function decorated as a Pydantic AI tool. No intermediary protocol (MCP) or CLI process needed.

```python
from pydantic_ai import Agent
from playwright.sync_api import sync_playwright

recovery_agent = Agent('openai:gpt-4o', tools=[navigate_and_render, find_audio_sources, ...])

@recovery_agent.tool_plain
def navigate_and_render(url: str) -> str:
    """Navigate to URL, wait for JS to render, return full HTML."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url, wait_until="networkidle")
        # inject cursor overlay, take screenshot, attach to Langfuse...
        html = page.content()
        browser.close()
        return html
```

The Pydantic AI agent calls these functions directly — same process, same thread, no serialization overhead.

### Why NOT the MCP server or CLI

| Approach | Problem |
|---|---|
| **Playwright MCP Server** | Requires Node.js runtime. Operates on accessibility-tree snapshots (not raw HTML). Reported latency issues with Pydantic AI (GitHub #2448). Screenshot attachment to Langfuse is indirect. Adds process management complexity. |
| **Playwright CLI** | The `npx playwright` CLI is for testing/codegen, not programmatic browser control. Can't capture network requests, inject JS, or return structured data. |
| **Direct Python API** | Same process, zero overhead, full access to `page.content()`, `page.screenshot()`, `page.on("response", ...)` for network capture, JS injection for cursor overlay. Langfuse attachment is trivial. |

Let me add this integration detail to the plan.

The integration is **direct Python API** — Playwright's `sync_playwright()` used inside Pydantic AI tool functions. Same process, same thread, zero overhead. No MCP server (needs Node.js, accessibility-tree abstraction, latency issues), no CLI (meant for testing, not programmatic control).

The agent calls `navigate(url)` → Pydantic AI invokes the Python function → Playwright talks to Chromium via CDP → returns HTML/screenshot → screenshot attached to Langfuse span. All in one process.

That's a much better architectural insight. Let me rethink this around separation of concerns:

1. **Pipeline** — does its job, emits rich signals with detailed context (what happened, why it failed, what was tried)
2. **Recovery layer** — a separate concern that subscribes to failures and decides the strategy: automatic retry → agentic recovery → human-in-the-loop escalation
3. The agent is just one of several possible recovery strategies, not hardwired into the pipeline

Let me redesign the plan around this event-driven, decoupled architecture.

Now let me redesign the plan around this decoupled architecture.

This is a much better architecture. Let me rewrite the plan around this decoupled design.

The plan is now restructured around three decoupled layers:

1. **Pipeline** — emits rich `StepFailureEvent` via a custom Django signal (structured error context, not just `str(exc)`)
2. **Recovery layer** — subscribes to failures, walks a configurable chain: retry (backoff) → agent (Pydantic AI) → human (escalation)
3. **Agent** — just one pluggable strategy behind a feature flag, not hardwired into the pipeline

The pipeline steps themselves change minimally (add `exc=exc` to `fail_step()` calls). The heavy lifting is in new modules (`events.py`, `recovery.py`) and a new `RecoveryAttempt` model. The agent is Phase 4, behind `RAGTIME_RECOVERY_AGENT_ENABLED=False`.

Let me examine the new Langfuse integration to understand what's already in place.

Good. The Langfuse integration is already in place with:

- **`episodes/observability.py`** — `is_enabled()`, `get_openai_client_class()`, `observe_step()`, `observe_provider()`, `set_observation_input/output()`, `_update_observation()`
- Uses Langfuse's **decorator-based approach** (`@observe()`, `propagate_attributes`) — not OpenTelemetry
- `ProcessingRun.pk` is used as `session_id` to group traces per pipeline run
- The OpenAI client is swapped to `langfuse.openai.OpenAI` when enabled (auto-traces all API calls)
- `langfuse>=4,<5` as optional dependency (`uv sync --extra observability`)

This means the plan should:
1. **Reuse** `observe_step()` and `observe_provider()` for recovery agent tracing
2. **Use** `_update_observation()` / `langfuse_context` to attach screenshots (not OTel/`LangfuseMedia` as previously assumed)
3. **Note**: Pydantic AI's OTel-based Langfuse integration would conflict with the existing decorator-based approach. The agent should use the existing observability module instead.

Let me update the plan to reflect this.

Now let me update the plan to account for the existing Langfuse integration.

The plan now accounts for the existing Langfuse integration. Key update: the agent won't use Pydantic AI's OTel-based `Agent.instrument_all()` (would conflict). Instead, it reuses the existing decorator-based approach — `@observe_step()` for the recovery function, `_update_observation()` for attaching screenshots, and `langfuse.openai.OpenAI` for auto-tracing LLM calls.

Good question. There's a real trade-off here. Let me lay out the options:

Good choice. The OTel migration becomes a prerequisite phase. Let me research how Langfuse's OTel endpoint works and what the migration entails, then update the plan.

Key finding: **Langfuse v4 is already OTel-native under the hood.** The `@observe()` and `propagate_attributes()` decorators already produce OTel spans internally. The migration is much smaller than expected — mainly replacing the `langfuse.openai.OpenAI` wrapper with `OpenAIInstrumentor().instrument()` so Pydantic AI shares the same OTel context.

Let me update the plan with this as a prerequisite phase.

Now update the implementation phases to include the OTel migration as Phase 0 and fix the key files table.

Also update the key files table to include the OTel migration files.

Plan updated. The OTel migration is now Phase 0 — a small, contained prerequisite:

1. Add `opentelemetry-instrumentation-openai` dependency
2. Add `setup()` to `observability.py` (calls `langfuse.get_client()` + `OpenAIInstrumentor().instrument()`)
3. Simplify OpenAI provider to use standard `openai.OpenAI` (instrumentation is now global)
4. Call `setup()` at Django startup in `AppConfig.ready()`

The existing `@observe_step()` and `@observe_provider()` decorators stay unchanged — they're already OTel-native in Langfuse v4. Pydantic AI's `Agent.instrument_all()` will then share the same OTel context automatically.

Good questions. Let me address both.

**On RetryStrategy:** You're right — if the pipeline steps don't typically fail transiently, a retry strategy adds complexity for little value. I'll remove it and simplify to just two strategies: agent → human.

**On OTel migration — potential functionality loss:**

The Langfuse docs reveal important nuances. Here's what I found:

**Langfuse SDK v4 is already OTel-native.** The `@observe()` decorator and `propagate_attributes()` create OTel spans under the hood. The SDK automatically sets up an OTel `TracerProvider`. This means **Pydantic AI's `Agent.instrument_all()` should work alongside the existing decorators** — they share the same OTel context.

**What we'd lose with a full OTel migration (replacing decorators with raw OTel):**

| Feature | Native SDK (`@observe`) | Raw OTel spans |
|---|---|---|
| Token usage/cost tracking | Auto-captured by `langfuse.openai.OpenAI` | Must manually set `langfuse.observation.usage_details` |
| Input/output on observations | `langfuse_context.update_current_observation()` | Must set `langfuse.observation.input` attribute |
| Session ID | `propagate_attributes(session_id=...)` | Must set `langfuse.session.id` attribute |
| Metadata queryability | Top-level, filterable | Lands in `metadata.attributes` unless prefixed correctly |
| Generation type detection | Automatic via wrapper | Only if span has `model` attribute |

**Revised recommendation:** We may NOT need a full migration. Since Langfuse v4 is already OTel-native, the existing decorators can coexist with Pydantic AI's OTel spans. The only change needed might be ensuring the Langfuse SDK is properly initialized at startup so both codepaths share the same `TracerProvider`.

Good — keep the SDK, ensure coexistence. Let me update the plan to reflect both decisions: drop RetryStrategy and simplify the Langfuse approach.

Now update the Langfuse section and the implementation phases.

Now update the implementation phases to remove Phase 0 (OTel migration) and simplify.

Also remove the `is_transient` and retry-related fields from `StepFailureEvent` since we're dropping RetryStrategy.

Also simplify the error classification since we don't need transient detection anymore.

Plan updated with both changes:

1. **Dropped RetryStrategy** — recovery chain is now just: agent → human. Simpler.
2. **No OTel migration** — Langfuse v4 is already OTel-native. Keep existing SDK decorators (`@observe_step`, `@observe_provider`, `langfuse.openai.OpenAI`). Just add `setup()` for eager TracerProvider initialization so Pydantic AI's `Agent.instrument_all()` shares the same OTel context automatically. No functionality loss.

Good catches. Let me clean up all remaining retry references and add success events + admin exposure.

I see several remaining "retry" references. Let me clean them all up, add success events, and add admin exposure for both event types.

Now add success events and update the signals section.

Now update the signals section to include both success and failure signals.

Now update the recovery tracking to remove the retry references, and add a `PipelineEvent` model for admin visibility of both success and failure events.

Now update the admin section to include both event types and the key files/phases.

Now update the key files table and implementation phases.

Let me do a final scan for any remaining "retry" references.

Good — all retry references are gone. The plan now has:

1. **Both success and failure events** — `StepCompletedEvent` + `StepFailureEvent`, both persisted as `PipelineEvent` records
2. **Admin visibility for both** — `PipelineEventInline` on episodes, standalone `PipelineEventAdmin` with filters
3. **Two recovery strategies** — agent → human (no retry)
4. **`NEEDS_REVIEW` removed entirely** (pre-v1, no backwards compat needed)
5. **Langfuse SDK kept as-is** — just add `setup()` for eager init + Pydantic AI coexistence

### User

[Request interrupted by user for tool use]
