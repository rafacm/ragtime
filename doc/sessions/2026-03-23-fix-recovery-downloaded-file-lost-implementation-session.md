# Fix: Recovery agent downloaded file lost — Implementation Session

**Date:** 2026-03-23

**Session ID:** 149517d5-483f-4daf-a6b6-60c04e032a9d

## Summary

Implemented the two-bug fix for recovery agent downloaded files being lost before the pipeline resumes. All 221 episode tests pass.

## Conversation

### User

Approved the plan and started implementation.

### Assistant

Implemented the fix in four steps:

**1. Fixed TemporaryDirectory race (`episodes/agents/agent.py`):** After the recovery agent completes in `_run_agent_async()`, added a check: if `output.downloaded_file` exists on disk, use `shutil.move` to relocate it from the temp dir to a stable `tempfile.mkstemp` path, and update the result's `downloaded_file` field. This runs before the `TemporaryDirectory` context manager exits.

**2. Updated scraping recovery (`episodes/agents/resume.py`):** Extracted `_save_audio_file()` helper (shared by both resume functions) that saves the MP3 to the episode's `audio_file` field and extracts duration via mutagen. Modified `_resume_from_scraping()` to check if `result.downloaded_file` exists on disk — if so, saves the file and resumes from TRANSCRIBING instead of DOWNLOADING. Falls back to the original DOWNLOADING resume when no file is available.

**3. Added test (`episodes/tests/test_agent_resume.py`):** Added `test_skips_download_when_file_already_downloaded` in `ResumePipelineScrapingTests`. Creates a temp MP3 file, passes both `audio_url` and `downloaded_file` in the result, and verifies the episode resumes from TRANSCRIBING with the file saved and duration extracted.

**4. Updated documentation (`doc/README.md`):** Added a sentence to the Recovery section explaining that when recovering from a scraping failure, if the agent both finds the audio URL and downloads the MP3 file using browser cookies, it skips the download step entirely and resumes directly from transcribing.

Ran `uv run python manage.py test episodes.tests.test_agent_resume -v 2` — all 3 tests pass. Ran `uv run python manage.py test episodes` — all 221 tests pass with no regressions.
