# Fix: Summarization should use episode language

## Problem

The summarization step (Step 7) generated summaries in English regardless of the episode's language. The episode model has a `language` field (ISO 639-1 code, e.g. `"de"`, `"es"`) set during scraping (Step 3), but the summarizer ignored it — `SUMMARIZE_SYSTEM_PROMPT` was a static string with no language instruction. The LLM defaulted to English, producing English summaries for German, Spanish, and other non-English episodes.

## Changes

- **`episodes/summarizer.py`**: Replaced the static `SUMMARIZE_SYSTEM_PROMPT` constant with a `build_system_prompt(language)` function. The base prompt is now stored in `_BASE_SYSTEM_PROMPT` (same content, minus the now-redundant "language the episode is in" bullet). When `language` is non-empty, the function appends `"Write the summary in {language_name}."` (e.g. "German"); when empty, it appends `"Write the summary in the same language as the transcript."`. An `ISO_639_LANGUAGE_NAMES` dict maps common ISO 639-1 codes to English names; unknown codes are passed through directly. `summarize_episode()` now calls `build_system_prompt(episode.language)` instead of referencing the static constant.

- **`episodes/tests.py`**: Updated `test_generate_called_with_correct_args` to set `language="de"` on the episode and assert that `"German"` appears in the system prompt. Added `test_generate_called_with_empty_language` to verify that an episode with `language=""` produces a prompt containing `"same language as the transcript"`.

## Key Parameters

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| `ISO_639_LANGUAGE_NAMES` | 14 common codes (de, en, es, fr, it, ja, ko, nl, pl, pt, ru, sv, tr, zh) | Covers all podcast languages likely encountered; unknown codes fall back to raw code |
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
| `episodes/tests.py` | Updated `test_generate_called_with_correct_args` to use `language="de"`; added `test_generate_called_with_empty_language` |
