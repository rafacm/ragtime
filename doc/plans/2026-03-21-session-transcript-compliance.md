# Plan: Session Transcript Compliance with AGENTS.md Guidelines

**Date:** 2026-03-21

## Context

An audit of all 40 files in `doc/sessions/` revealed widespread non-compliance with the AGENTS.md documentation guidelines. Issues fall into five categories: metadata ordering, Session ID format, filename conventions, conversation structure, and verbatim accuracy.

## Issue Summary

| Issue | Count |
|---|---|
| Not verbatim (summarized/rephrased/paraphrased) | 26 of 40 |
| SID before Date (should be Date→SID) | 28 |
| Filename missing `-planning/implementation-session.md` | 14 |
| SID under `##` heading or `## Sessions` list | 11 |
| Missing `## Summary` | 3 |
| Non-standard conversation format | 4 |

## Steps

### 1. Regenerate all 40 session transcripts

Write a Python script that, for each session file:

1. Reads the existing file to preserve the `# Title` and `## Summary` content.
2. Reads the corresponding JSONL session log.
3. Extracts user and assistant text messages verbatim.
4. Writes a new file with the correct structure:
   - `# Title` (line 1)
   - `**Date:** YYYY-MM-DD`
   - `**Session ID:** <UUID>`
   - `## Summary` (preserved from existing file)
   - `## Conversation` with `### User` / `### Assistant` sections containing verbatim text.

### 2. Rename files with incorrect filenames

The 14 pre-March-14 files that don't end in `-planning-session.md` or `-implementation-session.md` need renaming. Some of these are combined planning+implementation transcripts — they will be split into separate files (one per session UUID) or kept as implementation sessions if they only cover implementation.

### 3. Handle edge cases

- Files with `unavailable` or missing Session ID: keep as-is with `unavailable` marker.
- Files with missing JSONL logs: preserve existing content, fix structure only.
- Files with `## Sessions` lists (multiple UUIDs): split into separate files if possible, or use the primary session UUID.
- Files sharing the same UUID across planning+implementation: investigate and assign correct UUIDs.

### 4. Update AGENTS.md

The AGENTS.md updates (metadata ordering, verbatim requirement, filename conventions) were already made in the current working tree.

### 5. Generate documentation

- Plan document (this file)
- Feature document in `doc/features/`
- Planning session transcript in `doc/sessions/`
- Implementation session transcript in `doc/sessions/`

## Files Modified

- All 40 files in `doc/sessions/` (content fixes + up to 14 renames)
- `AGENTS.md` (already modified)
- New: `doc/features/2026-03-21-session-transcript-compliance.md`
- New: `doc/sessions/2026-03-21-session-transcript-compliance-planning-session.md`
- New: `doc/sessions/2026-03-21-session-transcript-compliance-implementation-session.md`

## Verification

After regeneration, re-run the audit script to confirm:
- All files start with `# Title`
- All files have `**Date:**` before `**Session ID:**`
- All files have inline `**Session ID:**`
- All files have `## Summary`
- All files use `### User` / `### Assistant` conversation format
- All filenames match `YYYY-MM-DD-*-(planning|implementation)-session.md`
- User messages match the first user message in the corresponding JSONL log
