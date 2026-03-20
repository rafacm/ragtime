# Agent Recovery Strategy for Pipeline Failures

**Date:** 2026-03-19

## Problem

Steps 2 (scraping) and 3 (downloading) in the pipeline sometimes fail — audio URLs hidden behind JavaScript players, downloads blocked by 403/CloudFlare. The decoupled recovery layer (Phase 3) emitted signals and walked a strategy chain, but `AgentStrategy` was a stub that always escalated to human. Every failure required manual admin intervention.

## Changes

### Recovery Agent (`episodes/agents/`)

A Pydantic AI agent with Playwright browser automation that can:

- Navigate to podcast episode pages in a headless Chromium browser
- Find audio URLs from `<audio>`, `<source>`, `<a>`, `<meta>` tags and data attributes
- Click play buttons and expand hidden players
- Download audio files through the browser (bypassing server-side blocks)
- Take screenshots for debugging (visible in Langfuse traces)

| Tool | Purpose |
|------|---------|
| `navigate_to_url` | Navigate browser, return page title + text snippet |
| `get_page_content` | Return current page text (truncated to 15k chars) |
| `find_audio_links` | Extract audio URLs from DOM elements |
| `click_element` | Click CSS selector, return resulting page state |
| `take_screenshot` | Screenshot with cursor dot, attach to Langfuse span |
| `download_file` | Download via browser, save to media directory |
| `extract_text_by_selector` | Get text content of matching elements |

All tools catch `PlaywrightError` and return error strings so the LLM can try alternative approaches instead of crashing.

### Pipeline Resume (`episodes/agents/resume.py`)

After successful recovery:

| Recovery type | Actions |
|---|---|
| Scraping | Set `audio_url`, status → `downloading`, `create_run(resume_from=downloading)` |
| Downloading | Save file via Django `File`, extract duration with `mutagen.MP3`, status → `transcribing`, `create_run(resume_from=transcribing)` |

### Admin Retry Action (`episodes/admin.py`)

"Retry with recovery agent" action on `RecoveryAttemptAdmin`:
- Available on `AWAITING_HUMAN` records
- Marks attempt as `RESOLVED` with `resolved_by="human:admin-retry"`
- Queues `_run_agent_recovery_task` via Django Q2 (non-blocking)
- Task creates a new `RecoveryAttempt` with the outcome

### Langfuse Observability

- Agent instrumented via `instrument=True` on `Agent` constructor
- Session ID: `recovery-run-{run_id}-episode-{episode_id}-attempt-{attempt_number}`
- Screenshots attached as `LangfuseMedia(content_type="image/png")` via `update_current_span`
- Explicit `client.flush()` after agent run to ensure traces reach the server

## Key Parameters

| Parameter | Value | Rationale |
|---|---|---|
| `request_limit` | 15 | Prevents runaway LLM costs per recovery attempt |
| Browser timeout | 30s | Per-operation Playwright default |
| `RAGTIME_RECOVERY_AGENT_TIMEOUT` | 120s | Overall recovery attempt timeout |
| Default model | `openai:gpt-4.1-mini` | Cost-effective, sufficient for page navigation |
| Page text truncation | 15,000 chars | Fits within LLM context without excessive tokens |
| Max recovery attempts | 5 | Inherited from recovery layer (prevents infinite loops) |

## Verification

1. Install: `uv sync --extra recovery && uv run playwright install chromium`
2. Configure: `RAGTIME_RECOVERY_AGENT_ENABLED=true`, `RAGTIME_RECOVERY_AGENT_API_KEY=...`
3. `uv run python manage.py test` — all 208 tests pass
4. Manual: submit episode with failing URL, enable agent, reprocess — agent finds audio URL and pipeline resumes
5. Langfuse: traces show agent spans with screenshots under `recovery-run-*` sessions

## Files Modified

| File | Change |
|------|--------|
| `pyproject.toml` | Add `recovery` optional dependency group |
| `episodes/agents/__init__.py` | New — export `run_recovery_agent` |
| `episodes/agents/deps.py` | New — `RecoveryDeps`, `RecoveryAgentResult` |
| `episodes/agents/browser.py` | New — `recovery_browser()` async context manager |
| `episodes/agents/tools.py` | New — 7 Playwright tool functions with error handling |
| `episodes/agents/agent.py` | New — Pydantic AI agent, Langfuse integration, sync wrapper |
| `episodes/agents/resume.py` | New — `resume_pipeline()` for scraping/downloading recovery |
| `episodes/recovery.py` | Replace `AgentStrategy.attempt()` stub with real implementation |
| `episodes/admin.py` | Add "Retry with recovery agent" action + `_run_agent_recovery_task` |
| `ragtime/settings.py` | Add `RAGTIME_RECOVERY_AGENT_{API_KEY,MODEL,TIMEOUT}` |
| `.env.sample` | Add 3 new env vars under recovery section |
| `README.md` | Add `### Recovery` section to Processing Pipeline |
| `core/management/commands/_configure_helpers.py` | Add 3 fields to Recovery subsystem |
| `core/management/commands/configure.py` | Broaden API key reuse check |
| `core/tests/test_configure.py` | Update mock inputs for new wizard fields |
| `episodes/tests/test_agent_tools.py` | New — unit tests for all 7 tools |
| `episodes/tests/test_agent_resume.py` | New — resume logic integration tests |
| `episodes/tests/test_recovery.py` | Extend with 3 AgentStrategy tests |
| `episodes/tests/test_admin.py` | Add 5 admin retry action + task tests |
