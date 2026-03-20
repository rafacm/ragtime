**Session ID:** a9ed7a68-194f-46f8-a9f7-57acad62df15
**Date:** 2026-03-20

# README Split — Planning Session

## Summary

Planned the split of the root README.md (276 lines) into a concise overview (~120 lines) and a detailed `doc/README.md`. Defined which sections to keep, replace, or move, and how to handle relative links and image assets.

## Detailed Conversation

### User

Entered plan mode and asked to plan splitting the root README into a concise landing page and a detailed doc/README.md.

### Assistant

Read the current README.md (276 lines) and analyzed its structure. Identified sections to keep in root (hero image, badges, What is RAGtime?, Features, Status, Getting Started, Tech Stack, License) and sections to move to doc/README.md (detailed pipeline steps, How Scott Works, LLM Observability/Langfuse).

Key decisions:
- **Pipeline section**: Replace ~90 lines of detailed step descriptions with a compact 10-row summary table. Link to doc/README.md for full details.
- **Image assets**: Move `ragtime.svg` and `ragtime.png` from project root to `doc/` since they are documentation assets.
- **Documentation section**: Add a new section in root README linking to all doc/ subdirectories (pipeline docs, architecture diagrams, feature docs, plans, session transcripts).
- **CHANGELOG link**: Move from Status section into the new Documentation section to avoid duplication.
- **Relative links**: All links in doc/README.md need adjustment (e.g., `episodes/signals.py` → `../episodes/signals.py`).

### User

Reviewed and accepted the plan. Asked to proceed with implementation.

### Assistant

Saved the plan and exited plan mode for implementation.
