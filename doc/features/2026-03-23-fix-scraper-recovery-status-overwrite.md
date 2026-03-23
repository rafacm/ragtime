# Fix pipeline bugs: scraper recovery overwrite + resolver wikidata_id overflow

**Date:** 2026-03-23

## Problem

Two pipeline bugs were blocking episode processing:

1. **Scraper recovery overwrite** — When LLM extraction returns incomplete metadata, the scraper calls `fail_step()` before `episode.save()`. Recovery runs synchronously inside `fail_step`, succeeds, and saves `status=TRANSCRIBING`. But the scraper's subsequent `save()` overwrites it back to `FAILED` from a stale local object. The pipeline gets stuck — the transcriber sees `status=failed` and exits early.

2. **Resolver wikidata_id overflow** — The resolving step crashes with `"value too long for type character varying(20)"` because the LLM returns malformed `wikidata_id` values (e.g., `"Q172}]} Explanation: "`) that exceed the `Entity.wikidata_id` field's `max_length=20`.

## Changes

### Scraper fix (`episodes/scraper.py`)

Split the single `episode.save()` into separate success and failure branches. The failure branch now saves **before** calling `fail_step()`, matching the pattern used by every other pipeline step function and the scraper's own exception handler.

### Resolver fix (`episodes/resolver.py`)

Added `_sanitize_qid()` — a regex-based function that extracts the bare Wikidata Q-ID (e.g., `Q172`) from whatever the LLM returns. Handles bare IDs, full URLs (`https://www.wikidata.org/wiki/Q93341`), trailing garbage (`Q172}]} Explanation:`), and empty strings. Applied at both points where `wikidata_id` is extracted from LLM output.

## Verification

- `uv run python manage.py test episodes` — all tests pass
- Regression test (`test_incomplete_metadata_does_not_overwrite_recovery_status`) connects a fake recovery handler to `step_failed` that sets `TRANSCRIBING`, asserts the scraper doesn't overwrite it
- `_sanitize_qid` verified against real LLM output patterns

## Files modified

| File | Change |
|------|--------|
| `episodes/scraper.py` | Split shared `episode.save()` into success/failure branches; failure saves before `fail_step()` |
| `episodes/tests/test_scraper.py` | Add regression test for recovery status preservation |
| `episodes/resolver.py` | Add `_sanitize_qid()` to extract bare Q-ID from LLM output; apply at both `wikidata_id` extraction points |
