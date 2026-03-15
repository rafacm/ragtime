# Session: README Pipeline Subsections — Implementation

**Date:** 2026-03-15

## Summary

Implemented the plan to convert the README's Processing Pipeline section from a numbered list to `###` subsections, correcting 6 step descriptions to match the actual implementation.

## Conversation

### User
Implement the plan to update the README pipeline section to subsection format.

### Assistant
Read the current `README.md` to locate the pipeline section (lines 34–48). Replaced the numbered list with 11 `###` subsections, each with the format `### N. EMOJI Name — \`status\`` followed by a corrected description paragraph.

Key description changes applied:
- Submit: "detected and notified" → "rejected"
- Scrape: added audio URL, LLM-based structured extraction, `needs_review` path
- Download: removed "Find", added duration extraction and conditional Resize skip
- Resize: added transcription API file-size limit rationale
- Summarize: added "in the episode's detected language"
- Chunk: added ~150-word target, segment boundaries, 1-segment overlap
- Resolve: clarified fuzzy matching, canonical records, episode links

Ran `uv run python manage.py check` — no issues found.

### User
Approved proceeding with branch creation, documentation, and PR.

### Assistant
Created branch `docs/readme-pipeline-subsections`. Created plan document (`doc/plans/readme-pipeline-subsections.md`), feature document (`doc/features/readme-pipeline-subsections.md`), and both session transcripts. Updated `CHANGELOG.md` with the new entry under the existing 2026-03-15 date section.
