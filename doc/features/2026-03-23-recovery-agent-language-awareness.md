# Recovery Agent Language Awareness and Visual Analysis

**Date:** 2026-03-23

## Problem

The recovery agent had no awareness of the episode's language. When browsing non-English podcast pages, it used English labels like "Information" and "Download" in CSS selectors, causing timeouts. It also had no way to find audio elements hidden behind visual UI patterns (three-dot menus, embedded players) or capture streaming audio URLs that don't appear in HTML source.

## Changes

### Language awareness

- Added `language: str` field to `RecoveryDeps` (ISO 639-1 code from the episode).
- Unified the two separate system prompts (`SCRAPING_SYSTEM_PROMPT`, `DOWNLOADING_SYSTEM_PROMPT`) into a single `RECOVERY_SYSTEM_PROMPT`. The agent receives `step_name`, `audio_url`, and `error_message` as context and adapts its approach.
- Added a conditional `LANGUAGE_SECTION` appended when the episode language is known. For non-English: instructs the agent to translate "Information", "More information", "Download" before using them in selectors. For English: tells the agent to use labels directly.

### Translation tool

- Added `translate_text` agent tool backed by a dedicated `RAGTIME_TRANSLATION_*` provider (provider, API key, model).
- Uses `ISO_639_RE` validation with fallback to the raw language code for valid but unlisted languages.
- Wrapped in try/except — falls back to returning original text on provider or LLM errors.
- Added to the shareable LLM provider group in the configuration wizard.

### Visual analysis tools

- **`analyze_screenshot`** — takes a screenshot and returns it as a Pydantic AI `BinaryImage` so the LLM can visually interpret the page (three-dot menus, play buttons, audio players).
- **`click_at_coordinates`** — clicks at pixel (x, y) position for elements found visually that aren't addressable by CSS selectors.
- **`intercept_audio_requests`** — listens for audio network requests (mp3, ogg, wav, aac, m4a) while clicking a selector or coordinates. Captures streaming URLs that don't appear in HTML.

### Download reliability

- Switched `download_file` from Playwright's `expect_download()` to `page.context.request.get()`. The browser's API request context shares cookies and session state, handling both direct downloads and streaming audio without requiring `Content-Disposition: attachment`.

### Langfuse trace isolation

- Recovery agent now detaches from the parent Langfuse/OTel context before creating its trace. Uses `opentelemetry.context.attach(Context())` to clear the inherited context so the recovery agent gets its own independent root trace, not nested under `scrape_episode`.

### Other improvements

- Increased request limit from 15 to 30 to accommodate additional tools.
- Added Playwright selector syntax guide to `click_element` docstring.
- Added `RAGTIME_TRANSLATION_*` env vars to `.env.sample` and Recovery section in docs.
- Added Excalidraw diagram for the Recovery layer.
- Mandatory screenshots after every agent action for full observability.
- Cookie-first download strategy: visit the episode page first to establish session, then navigate to audio URL.

## Key Parameters

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| `request_limit` | 30 | Increased from 15 to accommodate translate, visual analysis, and audio interception tools |
| `intercept_audio_requests` wait | 3 seconds | Time for network activity to settle after clicking play |
| `RAGTIME_TRANSLATION_MODEL` default | `gpt-4.1-mini` | Lightweight model sufficient for single-phrase translation |

## Verification

1. `uv run python manage.py test` — all 239 tests pass
2. Trigger a recovery run on a non-English episode (e.g. German) and verify in Langfuse:
   - Recovery agent has its own independent trace (not nested under `scrape_episode`)
   - `translate_text` is called before `click_element` on non-English pages
   - Screenshots appear after every action
3. Verify `manage.py configure` includes Translation in the shared LLM wizard flow

## Files Modified

| File | Change |
|------|--------|
| `episodes/agents/deps.py` | Added `language: str` field |
| `episodes/agents/agent.py` | Unified prompt, language sections, tool registration, OTel context detach, request limit |
| `episodes/agents/tools.py` | Added `translate_text`, `analyze_screenshot`, `click_at_coordinates`, `intercept_audio_requests`; rewrote `download_file`; added selector syntax to `click_element` |
| `episodes/providers/factory.py` | Added `get_translation_provider()` |
| `ragtime/settings.py` | Added `RAGTIME_TRANSLATION_*` settings |
| `.env.sample` | Added translation provider section |
| `core/management/commands/_configure_helpers.py` | Added Translation to shareable LLM system |
| `core/tests/test_configure.py` | Updated wizard tests for Translation subsystem |
| `episodes/tests/test_agent_tools.py` | Added tests for all new tools and error paths |
| `doc/README.md` | Updated Recovery section with all changes |
| `doc/architecture/ragtime-recovery.excalidraw` | Recovery layer diagram |
