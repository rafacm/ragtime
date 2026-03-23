# Fix: Recovery agent downloaded file is lost before pipeline resumes

**Date:** 2026-03-23

## Problem

Two bugs caused the recovery agent's downloaded file to be lost, making the pipeline restart at the Download step and get stuck:

1. **TemporaryDirectory race** — `_run_agent_async()` wrapped the agent run in a `TemporaryDirectory`. The temp dir was cleaned up before `AgentStrategy.attempt()` called `resume_pipeline()`, so `result.downloaded_file` always pointed to a deleted file.

2. **Scraping recovery ignored downloaded file** — `_resume_from_scraping()` only used `result.audio_url` and always resumed from DOWNLOADING. The signal queued `download_episode` which used `wget` (without browser cookies), so downloads that required session cookies would fail in a loop.

## Changes

### Persist downloaded file across temp dir cleanup (`episodes/agents/agent.py`)

After the recovery agent completes, if it downloaded a file, the file is moved out of the `TemporaryDirectory` to a stable temp path using `shutil.move` + `tempfile.mkstemp`. The result's `downloaded_file` path is updated before returning.

### Skip download step when file already available (`episodes/agents/resume.py`)

`_resume_from_scraping()` now checks if `result.downloaded_file` exists on disk. If so, it:
- Saves the file to the episode's `audio_file` field
- Extracts MP3 duration via mutagen
- Resumes from TRANSCRIBING (skipping the download step)
- Falls back to resuming from DOWNLOADING if no file is available

Extracted `_save_audio_file()` helper shared by both `_resume_from_scraping()` and `_resume_from_downloading()`.

### Documentation (`doc/README.md`)

Updated the Recovery section to document that when the agent both finds the audio URL and downloads the file during scraping recovery, it skips the download step and resumes directly from transcribing.

## Verification

```bash
uv run python manage.py test episodes.tests.test_agent_resume -v 2
uv run python manage.py test episodes
```

## Files modified

| File | Change |
|------|--------|
| `episodes/agents/agent.py` | Move downloaded file to stable temp path before `TemporaryDirectory` cleanup |
| `episodes/agents/resume.py` | Skip download step when file exists; extract `_save_audio_file()` helper |
| `episodes/tests/test_agent_resume.py` | Add `test_skips_download_when_file_already_downloaded` |
| `doc/README.md` | Document skip-download behavior in Recovery section |
