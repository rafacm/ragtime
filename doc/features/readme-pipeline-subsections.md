# Feature: README Pipeline Section — Subsection Format

## Problem

The README's "Processing Pipeline" section used a numbered list with one-line descriptions. Seven of the eleven step descriptions had drifted from the actual implementation, and the flat list format couldn't accommodate detailed content like entity type management without looking disproportionate.

## Changes

Converted the numbered list into `####` subsections under a new `### Steps` heading — one per pipeline step — with the format `#### N. EMOJI Name (status: \`...\`)`. The intro sentence was replaced with a description of the signal-based dispatch mechanism linking to `episodes/signals.py`.

### Description fixes

| Step | What changed |
|------|-------------|
| Submit | "detected and the user is notified" → "rejected" |
| Scrape | Added audio URL extraction, LLM-based structured extraction, `needs_review` path |
| Download | Removed misleading "Find"; added duration extraction and conditional Resize skip |
| Resize | Added rationale for the 25 MB threshold (transcription API file-size limit) |
| Transcribe | Minor rewording: "producing segment and word-level timestamps" |
| Summarize | Added "in the episode's detected language" |
| Chunk | Added ~150-word target, segment boundaries, 1-segment overlap |
| Extract | Unchanged (subsection format accommodates the detail naturally) |
| Resolve | Clarified: fuzzy matching, canonical records, episode links |
| Embed | Added "for transcript chunks" |
| Ready | Minor rewording |

## Key parameters

N/A — documentation-only change, no tunable constants.

## Verification

- Visual review of rendered markdown confirms correct heading levels and formatting
- `uv run python manage.py check` passes

## Files modified

| File | Change |
|------|--------|
| `README.md` | Replaced pipeline numbered list with `###` subsections, fixed 7 step descriptions |
