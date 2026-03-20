# Plan: Clarify Extract and Resolve README sections

**Date:** 2026-03-17

## Context

The README's pipeline steps 7 (Extract entities) and 8 (Resolve entities) are dense single-paragraph descriptions that don't clearly explain *what* each step does or *why* they're separate. We want to rewrite these sections to introduce NER/NEL concepts, add concrete examples, and explain the two-phase design — while keeping the existing code terminology ("extract", "extracting") unchanged.

## Changes

**File: `README.md`** — rewrite sections for steps 7 and 8 only.

### Step 7: Extract entities
- Add **NER** label and one-line description
- Explain per-chunk processing and that no DB records are created
- Add example table (Bird → musician, Birdland → music venue, Dizzy Gillespie → musician)
- Keep entity types list with correct Wikidata-aligned names
- Keep `load_entity_types` command block and admin notes
- Move "Raw extraction results are stored in `Chunk.entities_json`" from end to earlier in the text

### Step 8: Resolve entities
- Add **NEL** label and one-line description
- Break into numbered list: DB matching + Wikidata candidates
- Add example table showing surface forms collapsing (Bird/Charlie Parker/Yardbird → Charlie Parker Q103767)
- Add rationale paragraph for two-phase design
- Keep `lookup_entity` CLI commands

## Verification

- Review the rendered markdown for correct table formatting
- `uv run python manage.py test` — no code changes, but sanity check
- Confirm no other README sections were affected

## Files modified

- `README.md` — steps 7 and 8 only
