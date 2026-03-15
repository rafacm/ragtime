# Session: README Pipeline Subsections — Planning

**Session ID:** a25c155f-6751-4a1f-b711-5ad9f84f435e
**Date:** 2026-03-15

## Summary

Reviewed every pipeline step description in the README against the actual implementation, identified 7 mismatches and a format limitation, and produced a plan to convert the numbered list to `###` subsections with corrected descriptions.

## Conversation

### User
Switch to main branch and pull remote changes.

### Assistant
Switched to `main` and pulled latest. Branch was already up to date.

### User
Review the "Processing Pipeline" section in the README. For each of the steps, review the current implementation and verify if the summary description for the step corresponds to the current implementation. Suggest new steps that could be added or steps that could be merged.

### Assistant
Explored the codebase in depth: read `episodes/pipeline.py` for the full step sequence, `episodes/views.py` for submit/dedup logic, `episodes/providers/` for scraping/transcription/extraction implementations, `episodes/models.py` for status fields and entity types, and `episodes/management/commands/load_entity_types.py`.

Findings on description mismatches (7 steps):

- **Submit** — "notified" is vague; duplicates are actually rejected via `unique=True` constraint and form validation error
- **Scrape** — omits audio URL extraction (critical field) and the `needs_review` fallback path for missing required fields
- **Download** — says "find and download" but finding happens in Scrape; also omits duration extraction via mutagen and the conditional skip when file ≤ 25 MB
- **Resize** — doesn't explain *why* 25 MB (transcription API file-size limit)
- **Summarize** — doesn't mention it generates in the episode's detected language
- **Chunk** — too vague; doesn't mention the ~150-word target, segment boundaries, or 1-segment overlap
- **Resolve** — description is too terse; doesn't explain fuzzy matching, canonical records, or episode linking

No steps needed to be added or merged — the 11-step pipeline is accurate.

Additionally noted that the **Extract** step description is disproportionately long for a list item (entity type management details), which would fit better in a richer format.

### User
*(Entered plan mode)*

### Assistant
Wrote the plan to convert the numbered list to `###` subsections per step. The subsection format allows richer descriptions, keeps entity type details inline naturally, and gives each step a linkable anchor. Drafted corrected descriptions for all 11 steps.

### User
*(Approved the plan)*
