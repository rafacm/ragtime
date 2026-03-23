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

### User

Create a PR.

### Assistant

Created PR #83 with plan document, feature doc, session transcripts, and changelog entry. Also added two additional commits for pre-existing unstaged changes (pipeline diagrams and AGENTS.md SQLite → PostgreSQL update) and fixed a missing "Development" entry in the `doc/README.md` table of contents.

### User

Review PR comments.

### Assistant

Reviewed two comments from Copilot:

1. **Temp file deleted even on failure** (`resume.py`) — the `finally` block in `_resume_from_scraping()` always deleted the downloaded file, even if saving failed. This would destroy the only copy and prevent fallback to DOWNLOADING.
2. **`mkstemp` + `shutil.move` cross-platform issue** (`agent.py`) — `mkstemp` creates the destination file, then `shutil.move` tries to rename over it, which fails on Windows.

### User

Implement the review comment fixes.

### Assistant

Addressed both comments:

1. **Safe temp file cleanup (`resume.py`):** Moved `os.unlink` from `finally` block to after `episode.save()` succeeds. Added `except Exception` handler that logs a warning and falls through to the DOWNLOADING resume path, preserving the downloaded file for the fallback attempt.

2. **Portable mkstemp (`agent.py`):** Added `os.unlink(stable_path)` after `os.close(fd)` so `shutil.move` targets a non-existent path, avoiding cross-platform rename-over-existing issues.

All 3 agent resume tests pass.

### User

Review second round of PR comments and implement fixes.

### Assistant

Reviewed three new comments from Copilot:

1. **Unhandled exception in temp-file persistence (`agent.py:206`):** The `shutil.move` / `os.unlink` block could raise and abort the entire recovery. Wrapped the file persistence block in try/except OSError, logging a warning and clearing `output.downloaded_file` to fall back to the audio_url-only resume path.

2. **AGENTS.md change not mentioned in PR description:** The SQLite → PostgreSQL one-liner and diagram changes were not scoped in the PR description. Updated the PR description with an "Additional housekeeping" section listing all non-fix changes (diagrams, AGENTS.md, ToC fix, README extras note).

3. **Diagram deletions not explained:** Recovery-related elements were moved to the new `ragtime-processing-pipeline-with-recovery` diagram (included in this PR), not deleted. Explained this in the PR description and replied to the comment.

All 3 agent resume tests pass.
