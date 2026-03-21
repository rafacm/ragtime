# Session: Agent Recovery Strategy — Planning

**Date:** 2026-03-19
**Session ID:** a150a5a3-218f-44b4-a02b-cf90912619d7

## Summary

Planned the implementation of Phase 4: replacing the `AgentStrategy` stub with a real Pydantic AI agent that uses Playwright browser automation to recover from scraping and downloading failures.

## Conversation

### User

Phase 4: Agent Recovery Strategy for Pipeline Failures

  Context: Phases 1-3 (merged in PR #69) introduced a decoupled recovery architecture:
  - Pipeline steps emit structured step_failed signals with error classification
  - A recovery layer walks a strategy chain: Agent → Human Escalation
  - AgentStrategy in episodes/recovery.py is currently a stub — it always returns should_escalate=True and is gated behind
  RAGTIME_RECOVERY_AGENT_ENABLED=False
  - PipelineEvent and RecoveryAttempt models track all attempts with admin visibility

  Goal: Replace the stub AgentStrategy with a real Pydantic AI agent that can autonomously recover from scraping (step 2) and download
  (step 3) failures by finding audio URLs using browser automation.

  Technology decisions (from planning session d7842f79):
  - Pydantic AI — model-agnostic, type-safe, agent.run_sync() works in Django Q2 tasks
  - Playwright (direct Python API) — browser tools as Pydantic AI tool functions, headless-only
  - Langfuse integration — Agent.instrument_all() shares existing TracerProvider, screenshots attached as LangfuseMedia

  Key files:
  - Plan: doc/plans/decoupled-recovery-architecture.md (Phase 4 section)
  - Recovery layer: episodes/recovery.py (stub AgentStrategy to replace)
  - Events: episodes/events.py (StepFailureEvent with cached_data containing scraped HTML, error context)
  - Observability: episodes/observability.py (existing Langfuse setup)
  - Settings: RAGTIME_RECOVERY_AGENT_ENABLED, RAGTIME_RECOVERY_CHAIN

  Scope from the plan:
  - episodes/agents/ package
  - Pydantic AI agent with Playwright browser tools
  - Agent.instrument_all() for Langfuse tracing
  - Screenshots with cursor overlay for observability

Additionally to the above, we need to make sure that we can download the file. So we need to pass the directory where the files need to be downloaded to Playwright.

### Assistant

Let me check a few more details before writing the plan.

Now I have everything I need. Let me write the plan.

Good call on the dedicated API key — it follows the existing per-subsystem pattern and keeps the agent provider fully independent. I'll set up `RAGTIME_RECOVERY_AGENT_API_KEY` that gets passed to the Pydantic AI model constructor explicitly, so it works regardless of which provider/model string is configured.

Let me update the plan with both decisions.

Now update the agent.py section to reflect the API key handling and JS cursor approach.

### User

[Request interrupted by user for tool use]
