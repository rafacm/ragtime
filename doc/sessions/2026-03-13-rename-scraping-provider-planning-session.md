# Session: Rename RAGTIME_LLM_* → RAGTIME_SCRAPING_* — Planning

**Date:** 2026-03-13
**Session ID:** 75420318-d8a7-44a3-855c-0d067ea8cef2

## Summary

Planned the rename of `RAGTIME_LLM_*` environment variables to `RAGTIME_SCRAPING_*` and `get_llm_provider()` to `get_scraping_provider()`, aligning the scraping provider with the `RAGTIME_<PURPOSE>_*` naming convention.

## Conversation

### User

What are the `RAGTIME_LLM_*` environment variables used for?

### Assistant

There are three `RAGTIME_LLM_*` environment variables, configured in `ragtime/settings.py:149-151` and consumed by the LLM provider factory in `episodes/providers/factory.py`:

| Variable | Default | Purpose |
|----------|---------|---------|
| `RAGTIME_LLM_PROVIDER` | `openai` | Which LLM backend to use (`openai`, `anthropic`, etc.) |
| `RAGTIME_LLM_API_KEY` | *(empty — required)* | API key for authenticating with the chosen LLM provider |
| `RAGTIME_LLM_MODEL` | `gpt-4.1-mini` | Model name passed to the provider for inference |

They're used by `get_llm_provider()` (`episodes/providers/factory.py:6`) to instantiate the appropriate LLM provider class. That provider is then called during episode scraping to do **structured extraction** — parsing episode metadata (title, summary, audio URL, etc.) from scraped HTML using an LLM.

### User

Let's refactor then those environment varialbes to `RAGTIME_SCRAPPING_LLM_*`. Also refctor the name of the `get_llm_provider` method to reflect that it is the scrapping provider. Update the README to indicate that the provider value defaults to `openai` like in the other variables also shown there.

### Assistant

Now I have a clear picture. Let me note two things before writing the plan:

1. The existing naming convention for other providers is `RAGTIME_<PURPOSE>_*` (e.g., `RAGTIME_SUMMARIZATION_PROVIDER`, `RAGTIME_EXTRACTION_API_KEY`) — without "LLM" in the name. The user asked for `RAGTIME_SCRAPPING_LLM_*` which would be inconsistent.

2. The codebase uses "scraping" (one p) everywhere. "Scrapping" (two p's) is a different word.

Let me ask before finalizing.

This is the same task — the plan is already complete. Let me re-read it to confirm it's still accurate.

The plan is complete and covers all 5 files that need changes. No modifications needed.
