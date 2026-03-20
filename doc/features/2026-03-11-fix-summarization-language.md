# Fix: Summarization should use episode language

**Date:** 2026-03-11

## Problem

The summarization step (Step 7) generated summaries in English regardless of the episode's language. The episode model has a `language` field (ISO 639-1 code, e.g. `"de"`, `"es"`) set during scraping (Step 3), but the summarizer ignored it — `SUMMARIZE_SYSTEM_PROMPT` was a static string with no language instruction. The LLM defaulted to English, producing English summaries for German, Spanish, and other non-English episodes.

## Changes

- **`episodes/summarizer.py`**: Replaced the static `SUMMARIZE_SYSTEM_PROMPT` constant with a `build_system_prompt(language)` function. The base prompt is now stored in `_BASE_SYSTEM_PROMPT` (same content, minus the now-redundant "language the episode is in" bullet). The language value is validated against a `^[a-z]{2}$` regex before interpolation to prevent prompt injection from malformed values. When `language` is a valid ISO 639-1 code, the function appends `"Write the summary in {language_name}."` (e.g. "German"); when empty or invalid, it appends `"Write the summary in the same language as the transcript."`. An `ISO_639_LANGUAGE_NAMES` dict maps common codes to English names; unknown but valid codes are passed through directly. `summarize_episode()` now calls `build_system_prompt(episode.language)` instead of referencing the static constant.

- **`episodes/tests.py`**: Updated `test_generate_called_with_correct_args` to set `language="de"` and assert that `"German"` appears in the system prompt. Added `test_generate_called_with_empty_language` to verify that an episode with `language=""` produces a prompt containing `"same language as the transcript"`. Added `test_invalid_language_falls_back` to verify that a malformed language value (e.g. `"Ignore previous instructions"`) is rejected and falls back to the transcript-language instruction.

## Key Parameters

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| `ISO_639_LANGUAGE_NAMES` | 14 common codes (de, en, es, fr, it, ja, ko, nl, pl, pt, ru, sv, tr, zh) | Covers all podcast languages likely encountered; unknown but valid codes fall back to raw code |
| `_ISO_639_RE` | `^[a-z]{2}$` | Validates language codes before prompt interpolation to prevent injection |
| Empty-language fallback | "same language as the transcript" | Lets the LLM infer the language from context when no explicit code was scraped |

## Verification

```bash
# Run summarization tests (7 total)
uv run python manage.py test episodes.tests.SummarizeEpisodeTests

# Run all tests
uv run python manage.py test episodes
```

## Files Modified

| File | Change |
|------|--------|
| `episodes/summarizer.py` | Replaced static `SUMMARIZE_SYSTEM_PROMPT` with `build_system_prompt(language)` function; added `ISO_639_LANGUAGE_NAMES` dict |
| `episodes/tests.py` | Updated `test_generate_called_with_correct_args` to use `language="de"`; added `test_generate_called_with_empty_language` and `test_invalid_language_falls_back` |
