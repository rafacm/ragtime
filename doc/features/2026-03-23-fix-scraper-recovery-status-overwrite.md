# Fix scraper save overwriting recovery status

**Date:** 2026-03-23

## Problem

When the scraper's LLM extraction returns incomplete metadata (missing `audio_url`), the recovery agent runs synchronously and successfully sets the episode to `TRANSCRIBING`. However, the scraper then overwrites this status back to `FAILED` because its local object is stale. The pipeline gets stuck — the transcriber sees `status=failed` and exits early.

## Changes

In `episodes/scraper.py`, the incomplete-metadata code path called `fail_step()` before `episode.save()`. Recovery runs synchronously inside `fail_step` (via Django signal → `handle_step_failure` → `AgentStrategy` → `resume_pipeline`), and `resume_pipeline` fetches a fresh DB copy and saves `status=TRANSCRIBING`. But the scraper's subsequent `episode.save()` used the stale local object with `status=FAILED`, overwriting the recovery.

The fix splits the single `episode.save()` into separate success and failure branches. The failure branch now saves **before** calling `fail_step()`, matching the pattern used by every other pipeline step function (transcriber, downloader, summarizer, chunker, extractor, resolver) and the scraper's own exception handler.

## Verification

- `uv run python manage.py test episodes` — all tests pass
- New regression test (`test_incomplete_metadata_does_not_overwrite_recovery_status`) connects a fake recovery handler to the `step_failed` signal that sets `TRANSCRIBING`, then asserts the scraper does not overwrite it

## Files modified

| File | Change |
|------|--------|
| `episodes/scraper.py` | Split shared `episode.save()` into success/failure branches; failure saves before `fail_step()` |
| `episodes/tests/test_scraper.py` | Add regression test for recovery status preservation |
