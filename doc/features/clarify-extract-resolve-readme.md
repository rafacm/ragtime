# Feature: Clarify Extract and Resolve README Sections

## Problem

The README descriptions for pipeline steps 7 (Extract entities) and 8 (Resolve entities) were dense single paragraphs that didn't clearly explain what each step does, why they're separate, or how they relate to standard NLP concepts (NER and NEL). Readers had to infer the two-phase design rationale from implementation details.

## Changes

- **Step 7 rewritten** — added NER label, explained per-chunk processing with no DB records created, added example table showing entity extraction from a sample sentence, moved `Chunk.entities_json` mention earlier in the text
- **Step 8 rewritten** — added NEL label, broke resolution into numbered list (DB matching + Wikidata candidates), added example table showing surface forms collapsing into canonical entities, added rationale paragraph explaining the two-phase design

## Key Parameters

No tunable constants changed. Documentation-only change.

## Verification

```bash
uv run python manage.py test   # No code changes, sanity check only
```

Review rendered markdown tables for correct formatting.

## Files Modified

| File | Change |
|------|--------|
| `README.md` | Rewrote steps 7 and 8 with NER/NEL labels, examples, and two-phase rationale |
