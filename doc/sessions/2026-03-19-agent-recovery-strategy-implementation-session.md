# Session: Agent Recovery Strategy — Implementation

**Date:** 2026-03-19

## Summary

Implemented Phase 4 of the recovery architecture: replaced the `AgentStrategy` stub with a Pydantic AI agent using Playwright browser automation, added Django admin retry action, and integrated with Langfuse observability including screenshot attachments.

## Conversation

### User
Implement the plan for Phase 4: Agent Recovery Strategy for Pipeline Failures.

### Assistant
Read all relevant files (recovery.py, models.py, processing.py, events.py, signals.py, downloader.py, observability.py, settings.py, .env.sample, _configure_helpers.py, pyproject.toml, test_recovery.py). Created feature branch `feature/agent-recovery-strategy`.

Implemented all files in sequence:
1. Added `recovery` optional dependency group to `pyproject.toml`
2. Created `episodes/agents/` package: `__init__.py`, `deps.py`, `browser.py`, `tools.py`, `agent.py`, `resume.py`
3. Replaced `AgentStrategy.attempt()` stub in `episodes/recovery.py`
4. Added settings, .env.sample entries, configure wizard fields
5. Created tests: `test_agent_tools.py`, `test_agent_resume.py`, extended `test_recovery.py`
6. Updated `core/tests/test_configure.py` for new wizard fields

Fixed test failures: async mock setup for `download_file` tool, mocked `mutagen.MP3` for resume test, updated integration tests to mock `run_recovery_agent`.

### User
Asked about testing locally and whether migrations are needed.

### Assistant
No migrations needed — no model changes. Provided setup instructions: `uv sync --extra recovery`, `uv run playwright install chromium`, configure env vars, run tests.

### User
Asked about README and configuration wizard updates.

### Assistant
Added `### Recovery` section to README after `### Steps`, documenting the strategy chain, setup, and configuration. Updated the section to match the Langfuse documentation pattern (wizard first, then manual .env).

### User
Fixed `playwright install chromium` → `uv run playwright install chromium` in README since the command is inside the venv.

### User
Noted that the configuration wizard should allow reusing the shared LLM API key for the agent.

### Assistant
Changed `suffix == "API_KEY"` to `suffix.endswith("API_KEY")` in `configure.py` so the "Enter to reuse LLM key" prompt appears for `AGENT_API_KEY`.

### User
Asked about Langfuse session IDs and whether any Langfuse configuration is needed.

### Assistant
Discovered the agent wasn't propagating session/user attributes to Langfuse. Added `_run_with_langfuse()` wrapper using `propagate_attributes(session_id=..., user_id=..., metadata=...)`.

### User
Requested Django admin UI for triggering agent retries.

### Assistant
Added "Retry with recovery agent" action on `RecoveryAttemptAdmin`:
- Filters to `AWAITING_HUMAN` records
- Marks as `RESOLVED` with `resolved_by="human:admin-retry"`
- Queues `_run_agent_recovery_task` via Django Q2
- Task rebuilds `StepFailureEvent`, runs agent, creates new `RecoveryAttempt`
Added 5 tests for the action and task function.

### User
Reported `result_type` error from Pydantic AI.

### Assistant
Fixed: `result_type=RecoveryAgentResult` → `output_type=RecoveryAgentResult` (Pydantic AI 1.x renamed the parameter).

### User
Reported `Page.click: Timeout 30000ms exceeded` crashing the agent.

### Assistant
Added `PlaywrightError` catch to all page-interaction tools (`navigate_to_url`, `click_element`, `download_file`, `extract_text_by_selector`). Tools now return error strings so the LLM can try alternatives.

### User
Reported no Langfuse traces appearing.

### Assistant
Two fixes:
1. Replaced `Agent.instrument_all()` (called too late) with `instrument=True` on the `Agent` constructor
2. Added `_flush_langfuse()` in `finally` block of `run_recovery_agent()` to force-flush buffered OTel spans

### User
Reported screenshots not visible in Langfuse.

### Assistant
Two fixes:
1. Moved `_attach_screenshots()` inside the `propagate_attributes` context so events are associated with the trace
2. Changed `_attach_screenshots` to use `LangfuseMedia(content_bytes=png, content_type="image/png")` with `create_event`

### User
Still couldn't see screenshots inline in tool traces.

### Assistant
Added `client.update_current_span(output=media)` directly in the `take_screenshot` tool, attaching the PNG to the tool's own Langfuse span.

### User
Asked to add attempt number to Langfuse session IDs for distinguishing retries.

### Assistant
Changed session ID from `recovery-run-{run_id}-episode-{episode_id}` to `recovery-run-{run_id}-episode-{episode_id}-attempt-{attempt_number}`.

All 208 tests pass throughout.
