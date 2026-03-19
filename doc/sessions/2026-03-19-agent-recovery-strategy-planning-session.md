# Session: Agent Recovery Strategy — Planning

**Date:** 2026-03-19
**Session ID:** a150a5a3-218f-44b4-a02b-cf90912619d7

## Summary

Planned the implementation of Phase 4: replacing the `AgentStrategy` stub with a real Pydantic AI agent that uses Playwright browser automation to recover from scraping and downloading failures.

## Conversation

### User
Requested planning for Phase 4 of the recovery architecture — implementing the agent recovery strategy that was stubbed out in Phase 3 (PR #69).

### Assistant
Explored the codebase thoroughly: `episodes/recovery.py` (AgentStrategy stub), `episodes/models.py` (Episode, ProcessingRun, PIPELINE_STEPS), `episodes/processing.py` (create_run, fail_step), `episodes/events.py` (StepFailureEvent), `episodes/signals.py`, `episodes/downloader.py`, `episodes/observability.py`, `ragtime/settings.py`, `.env.sample`, `core/management/commands/_configure_helpers.py`, `pyproject.toml`, and existing tests.

Key findings:
- AgentStrategy stub always returns `should_escalate=True`
- Only handles `scraping` and `downloading` steps
- Recovery layer already has signal integration, max attempts (5), and RecoveryAttempt audit trail
- Observability uses Langfuse with `propagate_attributes` for session grouping
- `create_run(resume_from=...)` supports resuming pipeline from arbitrary steps

### Assistant
Designed the implementation plan with 10 steps:
1. Optional dependency group (`pydantic-ai`, `playwright`)
2. Browser lifecycle context manager
3. Dependencies dataclass + result model
4. 7 Playwright browser tools
5. Pydantic AI agent with dynamic system prompts
6. Pipeline resume logic (scraping → downloading, downloading → transcribing)
7. Replace AgentStrategy stub with lazy imports
8. Settings + configuration wizard updates
9. README documentation
10. Comprehensive tests

### User
Approved the plan.
