# Feature: Session Transcript Compliance with AGENTS.md Guidelines

**Date:** 2026-03-21

## Problem

An audit of all 40 original session transcript files in `doc/sessions/` revealed widespread non-compliance with the AGENTS.md documentation guidelines (after splits, the final count is 45 files):

- 26 files had rephrased, summarized, or paraphrased user messages instead of verbatim text
- 28 files had Session ID before Date (should be Date first)
- 14 files had filenames missing the `-planning-session.md` or `-implementation-session.md` suffix
- 11 files had Session ID under a `## heading` or `## Sessions` list instead of inline `**Session ID:**`
- 3 files were missing `## Summary` sections
- 4 files used non-standard conversation formats

## Changes

### 1. Regenerated all session transcripts from JSONL logs

Wrote a Python script that reads the Claude Code session JSONL logs, extracts user and assistant text messages verbatim, and writes compliant transcript files with the correct structure:

```
# Title
**Date:** YYYY-MM-DD
**Session ID:** UUID

## Summary
...

## Conversation

### User
(verbatim text)

### Assistant
(verbatim text)
```

### 2. Renamed 15 files to match naming convention

Pre-March-14 files that lacked the `-planning-session.md` / `-implementation-session.md` suffix were renamed. Single-session combined files became `-implementation-session.md`.

### 3. Split 4 combined transcripts

Files that covered both planning and implementation in one document but had separate session UUIDs were split into two files:

| Original | Planning UUID | Implementation UUID |
|---|---|---|
| `manage-py-configure` | `9a0dcfdd` | `3cb9e358` |
| `rename-scraping-provider` | `75420318` | `3d8500b6` |
| `step-09-resolve-entities` | `09ef4d53` | `5b6f037b` |
| `processing-status-tracking` | `ebcf8a85` | `b64c02cc` |

### 4. Fixed incorrect Session IDs

- `merge-resize-into-transcribe-implementation-session`: Was `0c231adc` (wrong — that's entity-types-to-db), corrected to `878af4b2`

### 5. Updated AGENTS.md format rules

- Session transcripts: metadata order is now Title → Date → Session ID (matching plans and features)
- Session ID placement: "after the `**Date:**` line" (not "at the top of the file")
- Verbatim requirement: "Do not rephrase, summarize, or paraphrase — copy the exact messages"
- Filename requirement: explicit `YYYY-MM-DD-` date prefix for session files

### 6. Updated CHANGELOG references

All 15 renamed session file references in CHANGELOG.md were updated to point to the new filenames. Combined `[session]` links were replaced with separate `[planning session]` and `[implementation session]` links.

## Key parameters

None — this is a documentation-only change.

## Verification

Run the compliance audit:
```bash
python3 -c "
import json, re, os
SESSION_DIR = 'doc/sessions'
for f in sorted(os.listdir(SESSION_DIR)):
    with open(os.path.join(SESSION_DIR, f)) as fh:
        lines = fh.read().split('\n')
    ok = lines[0].startswith('# ') and any(l.startswith('**Date:**') for l in lines[:10]) and any(l.startswith('**Session ID:**') for l in lines[:10])
    suffix_ok = f.endswith('-planning-session.md') or f.endswith('-implementation-session.md')
    status = 'OK' if ok and suffix_ok else 'FAIL'
    print(f'{status}: {f}')
"
```

## Files modified

| File | Change |
|---|---|
| `AGENTS.md` | Tightened metadata ordering, verbatim requirement, filename conventions |
| `CHANGELOG.md` | Updated 15 session file references, added 2026-03-21 entry |
| `doc/sessions/*.md` (45 files) | Regenerated with verbatim content, correct structure, and compliant filenames |
| `doc/plans/2026-03-21-session-transcript-compliance.md` | Plan document |
| `doc/features/2026-03-21-session-transcript-compliance.md` | This file |
