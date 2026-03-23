# Recovery Agent Language Awareness and Visual Analysis

**Date:** 2026-03-23

## Context

The Pydantic AI recovery agent browses podcast episode pages to find audio URLs when scraping/downloading fails. Many podcast pages are in non-English languages (German, Swedish, Spanish, etc.). The agent didn't know the episode's language, couldn't translate UI labels, and had no visual analysis capability for finding hidden UI elements.

## Goals

1. Pass episode language to the recovery agent
2. Add a translation tool so the agent can translate UI labels to the page's language
3. Unify the two separate system prompts (scraping/downloading) into one
4. Add visual analysis tools for finding hidden audio elements (three-dot menus, play buttons)
5. Add audio network interception to capture streaming URLs
6. Improve download reliability using the browser's request context

## Changes

| Change | Files |
|--------|-------|
| Add `language` to `RecoveryDeps` | `episodes/agents/deps.py` |
| Unified system prompt with language section | `episodes/agents/agent.py` |
| `translate_text` tool with dedicated provider | `episodes/agents/tools.py`, `episodes/providers/factory.py` |
| `RAGTIME_TRANSLATION_*` config | `ragtime/settings.py`, `.env.sample`, `core/management/commands/_configure_helpers.py` |
| `analyze_screenshot` tool (returns `BinaryImage`) | `episodes/agents/tools.py` |
| `click_at_coordinates` tool | `episodes/agents/tools.py` |
| `intercept_audio_requests` tool | `episodes/agents/tools.py` |
| Switch `download_file` to browser request context | `episodes/agents/tools.py` |
| Detach recovery agent from parent Langfuse trace | `episodes/agents/agent.py` |
| Playwright selector syntax in `click_element` docstring | `episodes/agents/tools.py` |
| Recovery section updates in docs | `doc/README.md` |
| Recovery layer Excalidraw diagram | `doc/architecture/ragtime-recovery.excalidraw` |
