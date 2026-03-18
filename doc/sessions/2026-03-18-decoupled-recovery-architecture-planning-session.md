# Session: Decoupled Recovery Architecture — Planning

**Session ID:** d7842f79-ffa8-4b5c-aa5c-336122a4a70d
**Date:** 2026-03-18

## Summary

Planned a decoupled recovery architecture for pipeline failures in steps 2 (scraping) and 3 (downloading). Evaluated agentic AI frameworks (recommended Pydantic AI), browser automation tools (recommended Playwright direct Python API), and Langfuse observability integration. Evolved from an initial "agent hardwired into pipeline" design to a three-layer architecture: pipeline emits rich events, a recovery layer walks an escalation chain (agent then human), and the agent is a pluggable strategy behind a feature flag. Key decisions included dropping retry strategies, keeping the existing Langfuse SDK (no OTel migration), adding both success and failure pipeline events with admin visibility, and removing the unused `NEEDS_REVIEW` status.

## Conversation

### User

Sometimes in Step 2 (Scraping) we fail to find the URL for the episode MP3 audio and sometimes we find it but the download is blocked by the website in Step 3. Let's analyze if this is a case where we could introduce agentic AI so that if those steps fail, we trigger an agent with the goal of obtaining the missing information and retrigering the pipeline from that step. Which agentic frameworks would be candidates for the implementation?

### Assistant

Explored the current scraping and download implementation to understand failure modes. Read `episodes/models.py`, `episodes/signals.py`, `episodes/scraper.py`, `episodes/downloader.py`, `episodes/pipeline.py`, `episodes/processing.py`, `episodes/admin.py`, and the provider abstractions in `episodes/providers/`. Used sub-agents to research the codebase architecture and evaluate agentic framework options.

Key findings from codebase exploration:
- Pipeline is orchestrated via Django signals with status transitions and `ProcessingRun`/`ProcessingStep` tracking
- Scraper uses `httpx` + `BeautifulSoup` to find audio URLs; fails if URL not found in HTML
- Downloader fetches audio via `httpx`; fails on 403/CloudFlare blocks
- Failures are permanent (`max_attempts: 1`), requiring manual admin intervention
- Provider abstraction uses ABC base classes with a factory pattern in `episodes/providers/`

Wrote the initial plan with framework analysis:

**Top recommendation: Pydantic AI** — model-agnostic, type-safe, lightweight, sync-compatible with Django Q2 via `agent.run_sync()`, right-sized for two single-agent recovery flows. Pydantic v2 already an indirect dependency, fully supports Python 3.13.

**Runner-up: OpenAI Agents SDK** — zero new dependencies (reuses existing `openai` package), but locks you to OpenAI models.

**Rejected alternatives:**
- LangGraph — heavy dependencies, complex graph abstraction for a single-agent problem
- CrewAI — multi-agent framework for what is fundamentally a single-agent task
- smolagents — code-execution security concerns in a Django context

**Key insight**: If the recovery strategies are deterministic ("try RSS, then headless browser, then give up"), a simple fallback chain would suffice. The agent approach pays off when the LLM needs to reason about which strategy to try based on the error and page content.

### Assistant (browser automation analysis)

Evaluated browser automation options for the recovery agent. Researched Playwright, Browser Use, Stagehand, Selenium, and Playwright MCP.

**Playwright (direct)** emerged as the clear winner:
- Headed/headless toggle is trivial — `launch(headless=False)` for dev, `True` for production, controlled via a single env var
- Right separation of concerns — Pydantic AI is the brain (decides strategy), Playwright provides the hands (navigate, click, extract, capture network). Each browser action is a clean, testable tool function
- No double-agent problem — Browser Use and Stagehand both have their own LLM agent loops, conflicting with Pydantic AI as orchestrator (double LLM calls, loss of control, cost multiplication)
- Sync API works natively in Django Q2 tasks. Lightweight dependency (one package + Chromium binary)

Rejected alternatives:
- **Browser Use** — adds its own agent loop, conflicts with Pydantic AI as orchestrator
- **Stagehand** — double LLM calls (every `act("click download")` triggers its own LLM), Python SDK is immature, no cursor in screenshots
- **Selenium** — heavier, less modern API, superseded by Playwright
- **Playwright MCP Server** — requires Node.js, accessibility-tree abstraction, reported latency issues with Pydantic AI (GitHub #2448)

### Assistant (headless-only with Langfuse observability)

Clarified that headed mode is off the table (server-only deployment). The real requirement is step-by-step screenshots with cursor position sent to Langfuse for observability. Researched Langfuse integration and revisited Stagehand.

Rejected Stagehand even with its open-source local mode:
1. **Double LLM calls**: Every `act("click download")` triggers Stagehand's own LLM to interpret the instruction — 2 LLM invocations per browser action (Pydantic AI + Stagehand). Expensive and opaque.
2. **No Langfuse integration**: Stagehand's internal LLM calls are invisible to Langfuse.
3. **No cursor in screenshots**: `auto_screenshot` exists but without cursor overlay.
4. **Python SDK is immature**: The TypeScript version is primary.

Recommended approach: **Custom Playwright wrapper + Langfuse**:
- Pydantic AI has production-ready Langfuse integration via OpenTelemetry — `Agent.instrument_all()` and every tool call, LLM call, and agent step becomes a Langfuse trace
- Screenshots with cursor: inject a small CSS overlay (~40 lines of JS) rendering a red dot at cursor position. `page.screenshot()` captures it.
- Attach screenshots to Langfuse via `LangfuseMedia(content_bytes=png_bytes, content_type="image/png")` on each span
- Single agent loop: only Pydantic AI reasons, Playwright executes deterministic actions. 1 LLM call per step, not 2.

### Assistant (Playwright integration approach)

Determined the integration is **direct Python API** — Playwright's `sync_playwright()` used inside Pydantic AI tool functions. Same process, same thread, zero overhead. No intermediary protocol (MCP) or CLI process needed.

Each browser action becomes a plain Python function decorated as a Pydantic AI tool. The agent calls `navigate(url)` -> Pydantic AI invokes the Python function -> Playwright talks to Chromium via CDP -> returns HTML/screenshot -> screenshot attached to Langfuse span. All in one process.

Rejected MCP server (needs Node.js, accessibility-tree abstraction, latency issues) and CLI (meant for testing/codegen, not programmatic control).

### Assistant (decoupled architecture redesign)

Arrived at a key architectural insight: the pipeline and recovery are separate concerns. Redesigned the plan around three decoupled layers:

1. **Pipeline layer** (existing) — does its job, emits rich signals with detailed context via custom Django signals (`step_completed`, `step_failed`). Structured error context in `StepFailureEvent`, not just `str(exc)`.
2. **Recovery layer** (new: `episodes/recovery.py`) — subscribes to failures, walks a configurable escalation chain: agent -> human. Each strategy implements `can_handle(event)` -> `attempt(event)`. Records every attempt in `RecoveryAttempt` model.
3. **Agent layer** — just one pluggable strategy behind a feature flag (`RAGTIME_RECOVERY_AGENT_ENABLED=False`), not hardwired into the pipeline.

Pipeline steps change minimally (add `exc=exc` to `fail_step()` calls). Heavy lifting is in new modules (`events.py`, `recovery.py`) and new models.

### Assistant (Langfuse integration with existing setup)

Examined the existing Langfuse integration in `episodes/observability.py`. Found:
- `is_enabled()`, `get_openai_client_class()`, `observe_step()`, `observe_provider()`, `set_observation_input/output()`, `_update_observation()`
- Uses Langfuse's **decorator-based approach** (`@observe()`, `propagate_attributes`) — not OpenTelemetry
- `ProcessingRun.pk` is used as `session_id` to group traces per pipeline run
- OpenAI client swapped to `langfuse.openai.OpenAI` when enabled (auto-traces all API calls)
- `langfuse>=4,<5` as optional dependency (`uv sync --extra observability`)

Initially planned to use Pydantic AI's OTel-based `Agent.instrument_all()`, but realized it would conflict with the existing decorator-based approach. Updated plan to reuse existing observability module instead.

### Assistant (OTel coexistence evaluation)

Explored whether to migrate existing Langfuse integration to OTel or keep the SDK. Key finding: **Langfuse v4 is already OTel-native under the hood** — the `@observe()` and `propagate_attributes()` decorators already produce OTel spans internally.

Evaluated what would be lost with a full OTel migration (replacing decorators with raw OTel):

| Feature | Native SDK (`@observe`) | Raw OTel spans |
|---|---|---|
| Token usage/cost tracking | Auto-captured by `langfuse.openai.OpenAI` | Must manually set attributes |
| Input/output on observations | `langfuse_context.update_current_observation()` | Must set attributes manually |
| Session ID | `propagate_attributes(session_id=...)` | Must set `langfuse.session.id` attribute |
| Metadata queryability | Top-level, filterable | Lands in `metadata.attributes` unless prefixed |
| Generation type detection | Automatic via wrapper | Only if span has `model` attribute |

Decision: **keep the existing SDK, ensure coexistence**. Just add `setup()` for eager `TracerProvider` initialization so Pydantic AI's `Agent.instrument_all()` shares the same OTel context automatically. No functionality loss, no migration risk. Both codepaths (SDK decorators and Pydantic AI OTel) share the same `TracerProvider`.

### Assistant (simplification: drop RetryStrategy)

Removed `RetryStrategy` from the recovery chain. Pipeline steps don't typically fail transiently — scraping failures are structural (URL not in HTML), download blocks are persistent (403/CloudFlare). A retry strategy with backoff adds complexity for little value.

Recovery chain simplified to just two strategies: agent -> human.

Also removed `is_transient` field and transient detection from `StepFailureEvent` and error classification. Cleaned up all retry references throughout the plan document.

### Assistant (success events and admin visibility)

Added success events alongside failure events for full pipeline observability:

- `StepCompletedEvent` + `StepFailureEvent`, both persisted as `PipelineEvent` records
- `PipelineEventInline` on `EpisodeAdmin` for both event types
- Standalone `PipelineEventAdmin` with filters
- `RecoveryAttemptInline` on `EpisodeAdmin`
- "Needs Human Action" list filter
- Reprocess action that resolves `AWAITING_HUMAN` records

Removed `NEEDS_REVIEW` from `Episode.Status` entirely (pre-v1, no backwards compatibility needed).

### Assistant (final plan)

Cleaned up all remaining retry references and finalized the plan with four implementation phases:

1. **Phase 1: Event infrastructure** — `events.py` with `StepCompletedEvent`/`StepFailureEvent` dataclasses, `classify_error()`, `PipelineEvent` and `RecoveryAttempt` models (migration), remove `NEEDS_REVIEW`, custom signals, modify `complete_step()`/`fail_step()` to emit events, pass `exc=exc` in each pipeline step's except block
2. **Phase 2: Recovery layer** — `recovery.py` with `RecoveryStrategy` ABC, dispatcher, `HumanEscalationStrategy` creating `AWAITING_HUMAN` records, stub `AgentStrategy` (always escalates, behind feature flag), wire signal handler in `apps.py`, recovery settings in `settings.py`/`.env.sample`
3. **Phase 3: Admin integration** — `PipelineEventInline` on `EpisodeAdmin`, standalone `PipelineEventAdmin` with filters, `RecoveryAttemptInline`, "Needs Human Action" filter, reprocess action resolves `AWAITING_HUMAN` records
4. **Phase 4: Agent strategy (future PR)** — `episodes/agents/` package, Pydantic AI agent with Playwright browser tools, `Agent.instrument_all()` for Langfuse tracing

Key design decisions:
- Pipeline events use custom Django signals (not model signals) for structured context
- `PipelineEvent` model holds all structured data (no `error_context` on `ProcessingStep`)
- Infinite loop prevention via attempt count ceiling (5 per episode+step)
- Agent strategy behind feature flag, stub in Phases 1-3
- Langfuse SDK kept as-is with OTel coexistence for Pydantic AI

Saved the plan to `doc/plans/decoupled-recovery-architecture.md`.
