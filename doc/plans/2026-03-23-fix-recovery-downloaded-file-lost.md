# Fix: Recovery agent downloaded file is lost before pipeline resumes

**Date:** 2026-03-23

## Context

When the recovery agent succeeds for a scraping failure, it finds the audio URL **and** downloads the MP3 file (the system prompt instructs it to: "If you find a working URL, use download_file to save it"). However, the pipeline restarts at the Download step and gets stuck because:

1. **`_resume_from_scraping()` ignores the downloaded file** — it only uses `result.audio_url`, sets status to `DOWNLOADING`, and the signal queues `download_episode` which re-downloads using `wget` (without browser cookies). If the URL requires cookies/auth (which is why scraping failed in the first place), `wget` fails too.

2. **TemporaryDirectory race condition** — Even for downloading recovery, the temp dir in `_run_agent_async()` is cleaned up **before** `resume_pipeline()` is called by `AgentStrategy.attempt()`. So `result.downloaded_file` always points to a deleted file.

### Bug trace (scraping recovery)

```
scraping fails → recovery agent finds URL + downloads file → _run_agent_async returns →
TEMP DIR DELETED → _resume_from_scraping() ignores downloaded_file →
sets status=DOWNLOADING → signal queues download_episode →
wget fails (no cookies) → FAILED → recovery for "downloading" →
agent downloads again → temp dir deleted again →
_resume_from_downloading() can't open file → FileNotFoundError →
escalates to human
```

## Two bugs to fix

### Bug 1: TemporaryDirectory cleaned up too early (`episodes/agents/agent.py`)

`_run_agent_async()` wraps the agent run in a `TemporaryDirectory` context manager. The temp dir is deleted when the `with` block exits. By the time `AgentStrategy.attempt()` calls `resume_pipeline()`, the downloaded file is gone.

**Fix:** Move the file out of the temp dir before returning. Use `shutil.move` to copy `result.downloaded_file` to a stable `tempfile.mkstemp` location and update the result's path before returning.

### Bug 2: Scraping recovery ignores downloaded file (`episodes/agents/resume.py`)

`_resume_from_scraping()` only uses `result.audio_url` and always resumes from DOWNLOADING. When the recovery agent also downloaded the file, it should skip the download step and resume from TRANSCRIBING instead.

**Fix:** In `_resume_from_scraping()`, check if `result.downloaded_file` exists on disk. If so, save the file to the episode's `audio_file` field, extract duration, and resume from TRANSCRIBING. Extract shared file-saving logic into `_save_audio_file()` helper.

## Files to modify

| File | Change |
|------|--------|
| `episodes/agents/agent.py` | Move downloaded file to stable temp path before `TemporaryDirectory` cleanup |
| `episodes/agents/resume.py` | Skip download step when file already downloaded; extract `_save_audio_file()` helper |
| `episodes/tests/test_agent_resume.py` | Add test for scraping recovery with downloaded file |
| `doc/README.md` | Document skip-download behavior in Recovery section |

## Verification

1. Run existing tests: `uv run python manage.py test episodes.tests.test_agent_resume`
2. New test: scraping recovery with `downloaded_file` set should resume from TRANSCRIBING, not DOWNLOADING
3. Run all episode tests to check for regressions: `uv run python manage.py test episodes`
