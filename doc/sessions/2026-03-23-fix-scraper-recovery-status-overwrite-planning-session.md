# Fix scraper recovery status overwrite — Planning session

**Date:** 2026-03-23

**Session ID:** 87080f37-fafd-4e80-9ce2-cb27c8dc0bb8

## Summary

Diagnosed a bug where the scraper's `episode.save()` overwrites the recovery status set by the agent, causing the pipeline to get stuck at the transcribing step.

### User

I tested with one podcast, I can see that the first processing run failed at "scraping" with "Incomplete metadata: missing required fields" because the MP3 URL could not be found. The agent strategy was successful with the message "Audio file found and downloaded successfully.". I can see another processing run resumed from step "transcribing" but it seems to get stuck there because the "started at" column does not have any values. In the logs I can see:

```
Episode 1: incomplete metadata after scraping
15:34:34 [Q] INFO Processed 'episodes.scraper.scrape_episode' (twenty-coffee-floor-butter)
15:34:35 [Q] INFO Process-7c3989a46edc4126afa87ea17472facd processing whiskey-zebra-illinois-fix 'episodes.transcriber.transcribe_episode'
Episode 1 has status 'failed', expected 'transcribing'
15:34:35 [Q] INFO Processed 'episodes.transcriber.transcribe_episode' (whiskey-zebra-illinois-fix)
```

### Assistant

Explored the full pipeline execution flow: `signals.py` (status-driven async task queuing), `scraper.py` (LLM extraction + incomplete metadata handling), `processing.py` (step lifecycle — `start_step`, `complete_step`, `fail_step`), `recovery.py` (strategy chain), and `agents/resume.py` (pipeline resumption after agent recovery).

Traced the execution timeline and identified the root cause: in `scraper.py` lines 138–167, the incomplete-metadata path calls `fail_step()` (line 146) before `episode.save()` (line 155). Recovery runs synchronously inside `fail_step` via Django signal — the agent succeeds and `resume_pipeline()` fetches a fresh DB copy, saves it with `status=TRANSCRIBING`, and queues `transcribe_episode`. But then control returns to the scraper, which saves its stale local object with `status=FAILED`, overwriting the recovery.

The exception handler (lines 169–174) doesn't have this bug because it saves first, then calls `fail_step()`. Audited all other pipeline step functions — they all follow the correct `save()` then `fail_step()` pattern. Only the scraper's incomplete-metadata path has the reversed order.

Proposed fix: split the shared `episode.save()` into separate success/failure branches, with the failure branch saving before `fail_step()`.
