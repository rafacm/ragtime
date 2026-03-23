# Fix pipeline bugs: scraper recovery overwrite + resolver wikidata_id overflow

**Date:** 2026-03-23

## Problem 1: Scraper save overwrites recovery status

When the scraper finds incomplete metadata, it calls `fail_step()` before `episode.save()`. The `fail_step` triggers recovery synchronously via Django signal — the agent recovers successfully and `resume_pipeline()` saves the episode with `status=TRANSCRIBING`. But then control returns to the scraper, which still holds a stale local `episode` object with `status=FAILED`, and its `episode.save()` overwrites `TRANSCRIBING` back to `FAILED`.

The queued `transcribe_episode` task then sees `status=failed` instead of `transcribing` and exits early — the pipeline gets stuck.

### Timeline

```
scraper.py  episode.status = FAILED           (local object)
scraper.py  fail_step(...)                     (synchronous signal)
  → recovery   handle_step_failure(...)
    → agent     resume_pipeline(...)
      →         Episode.objects.get(pk=...)    (fresh DB copy)
      →         episode.status = TRANSCRIBING
      →         episode.save(...)              (DB: TRANSCRIBING)
      →         signal queues transcribe_episode
scraper.py  episode.save(...)                  (DB overwritten: FAILED!)
```

### Fix

Split the shared `episode.save()` into success/failure branches so the failure path saves **before** calling `fail_step()` — matching the pattern every other step function already uses.

## Problem 2: Resolver crashes with "value too long for type character varying(20)"

The resolving step crashes because the LLM returns malformed `wikidata_id` values (e.g., `"Q172}]} Explanation: "`) that exceed the `Entity.wikidata_id` field's `max_length=20`. The LLM response is saved directly to the DB without sanitization.

### Fix

Add a `_sanitize_qid()` function that extracts the bare Q-ID (e.g., `Q172`) from the LLM response using regex `Q\d+`. Apply it at both points where `wikidata_id` is extracted from LLM output in `resolver.py`.

## Verification

- All existing tests pass
- Regression test for scraper: simulates recovery changing status during `fail_step` signal, asserts scraper does not overwrite it
- `_sanitize_qid` handles bare IDs, full URLs, trailing garbage, and empty strings
