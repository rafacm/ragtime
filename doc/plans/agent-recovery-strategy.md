# Phase 4: Agent Recovery Strategy for Pipeline Failures

## Context

Steps 2 (scraping) and 3 (downloading) in the RAGtime pipeline sometimes fail — audio URLs not found in HTML, downloads blocked by 403/CloudFlare. The decoupled recovery layer (Phases 1-3, PR #69) already emits `StepFailureEvent` signals and walks a strategy chain (agent → human), but `AgentStrategy` is a stub that always escalates. This phase replaces the stub with a real Pydantic AI agent that uses Playwright browser automation to find audio URLs and download files.

## Package Structure

```
episodes/agents/
    __init__.py      # exports run_recovery_agent()
    deps.py          # RecoveryDeps dataclass + RecoveryAgentResult model
    agent.py         # Pydantic AI agent definition, system prompt, run function
    tools.py         # Playwright browser tool functions
    browser.py       # Browser lifecycle context manager
    resume.py        # Pipeline resume logic after successful recovery
```

## Implementation Steps

1. **Add dependencies** — `recovery` optional group in `pyproject.toml` with `pydantic-ai>=0.1` and `playwright>=1.40`
2. **Browser lifecycle** — `recovery_browser()` async context manager: headless Chromium, custom user-agent, 30s timeout, download directory
3. **Dependencies + result model** — `RecoveryDeps` dataclass (episode data, Playwright page, mutable screenshots list), `RecoveryAgentResult` Pydantic model
4. **7 Playwright tools** — `navigate_to_url`, `get_page_content`, `find_audio_links`, `click_element`, `take_screenshot`, `download_file`, `extract_text_by_selector`. All catch `PlaywrightError` and return error strings so the LLM can retry
5. **Pydantic AI agent** — dynamic system prompt (scraping vs downloading), 15-request limit, Langfuse instrumentation via `instrument=True`, `propagate_attributes` for session grouping, explicit flush after run
6. **Pipeline resume** — scraping recovery sets `audio_url` + resumes from downloading; download recovery saves file + extracts duration + resumes from transcribing
7. **Replace AgentStrategy stub** — lazy imports in `attempt()` body, success → `resume_pipeline`, failure/exception → escalate
8. **Admin retry action** — "Retry with recovery agent" on `RecoveryAttemptAdmin` for `AWAITING_HUMAN` records, queues async Django Q2 task
9. **Settings + configuration** — 3 new env vars (`AGENT_API_KEY`, `AGENT_MODEL`, `AGENT_TIMEOUT`), configuration wizard fields, `.env.sample`
10. **README** — `### Recovery` section after `### Steps` documenting the strategy chain, setup, and configuration

## Files Modified

| File | Change |
|------|--------|
| `pyproject.toml` | Add `recovery` optional dependency group |
| `episodes/agents/__init__.py` | New — export `run_recovery_agent` |
| `episodes/agents/deps.py` | New — `RecoveryDeps`, `RecoveryAgentResult` |
| `episodes/agents/browser.py` | New — `recovery_browser()` context manager |
| `episodes/agents/tools.py` | New — 7 Playwright tool functions |
| `episodes/agents/agent.py` | New — Pydantic AI agent, `run_recovery_agent()` |
| `episodes/agents/resume.py` | New — `resume_pipeline()` |
| `episodes/recovery.py` | Replace `AgentStrategy.attempt()` stub |
| `episodes/admin.py` | Add "Retry with recovery agent" action + async task |
| `ragtime/settings.py` | Add 3 recovery agent settings |
| `.env.sample` | Add 3 new env vars |
| `README.md` | Add Recovery section to Processing Pipeline |
| `core/management/commands/_configure_helpers.py` | Add 3 fields to Recovery subsystem |
| `core/management/commands/configure.py` | Broaden API key reuse to `endswith("API_KEY")` |
| `core/tests/test_configure.py` | Update mock inputs for new fields |
| `episodes/tests/test_agent_tools.py` | New — tool unit tests |
| `episodes/tests/test_agent_resume.py` | New — resume logic tests |
| `episodes/tests/test_recovery.py` | Extend with AgentStrategy tests |
| `episodes/tests/test_admin.py` | Add admin retry action + task tests |
