# Fix: Recovery agent downloaded file lost — Planning Session

**Date:** 2026-03-23

**Session ID:** 149517d5-483f-4daf-a6b6-60c04e032a9d

## Summary

Investigated a bug where the recovery agent successfully retrieves an audio MP3 URL and downloads the file, but the pipeline restarts at the Download step and gets stuck. Identified two root causes and designed a fix.

## Conversation

### User

When the recovery agent is successful and is able to retrieve the audio MP3 URL and download the file, it seems that the pipeline is started again in the "Download" step and it gets stuck there. Can you verify this?

### Assistant

Explored the recovery agent flow across `episodes/agents/agent.py`, `episodes/agents/resume.py`, `episodes/signals.py`, `episodes/downloader.py`, and `episodes/recovery.py`. Traced the full execution path for both scraping and downloading recovery scenarios.

Confirmed two bugs:

**Bug 1 — TemporaryDirectory race condition:** In `_run_agent_async()`, the agent downloads files to a `TemporaryDirectory`. The `with` block cleans up the temp dir when `return result.output` exits the context manager. By the time `AgentStrategy.attempt()` calls `resume_pipeline()`, the `downloaded_file` path points to a deleted file.

**Bug 2 — Scraping recovery ignores downloaded file:** `_resume_from_scraping()` only uses `result.audio_url` and sets status to `DOWNLOADING`. This queues `download_episode` which uses `wget` without browser cookies. If the URL requires session cookies (common for sites that also blocked scraping), `wget` fails. The recovery agent already downloaded the file using browser cookies, but the file is both deleted (Bug 1) and ignored (Bug 2).

The net effect is a failure loop: recovery succeeds → file deleted → pipeline restarts download → wget fails → recovery runs again → until max attempts.

Wrote the plan proposing: (1) move the downloaded file to a stable temp path before the `TemporaryDirectory` is cleaned up, and (2) make `_resume_from_scraping()` use the downloaded file when available, skipping directly to TRANSCRIBING.

### User

Make sure we document this change in the doc/README.

### Assistant

Updated the plan to include updating `doc/README.md`'s Recovery section to document that when the agent both finds the audio URL and downloads the file during scraping recovery, it skips the download step and resumes directly from transcribing.
