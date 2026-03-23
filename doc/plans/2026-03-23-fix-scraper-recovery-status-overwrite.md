# Fix scraper save overwriting recovery status

**Date:** 2026-03-23

## Problem

When the scraper finds incomplete metadata, it calls `fail_step()` before `episode.save()`. The `fail_step` triggers recovery synchronously via Django signal — the agent recovers successfully and `resume_pipeline()` saves the episode with `status=TRANSCRIBING`. But then control returns to the scraper, which still holds a stale local `episode` object with `status=FAILED`, and its `episode.save()` overwrites `TRANSCRIBING` back to `FAILED`.

The queued `transcribe_episode` task then sees `status=failed` instead of `transcribing` and exits early — the pipeline gets stuck.

## Timeline

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

## Fix

Split the shared `episode.save()` into success/failure branches so the failure path saves **before** calling `fail_step()` — matching the pattern every other step function already uses.

## Verification

- All existing tests pass
- New regression test simulates recovery changing status during `fail_step` signal and asserts the scraper does not overwrite it
