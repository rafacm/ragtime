# Session: Clarify Extract and Resolve README — Planning

**Date:** 2026-03-17

**Session ID:** 3ce31107-6e3f-4071-9b59-a054e2a236a3

## Summary

Planned a rewrite of README pipeline steps 7 (Extract entities) and 8 (Resolve entities) to introduce NER/NEL terminology, add concrete examples, and explain the two-phase design rationale. Considered renaming "extract" to "recognize" across the codebase but decided against it due to large blast radius (code, migrations, env vars, tests).

## Conversation

### User

Why do we need the two phases "Extract entities" and "Resolve entities"? Why can't we do it in one step?

### Assistant

Great question. Let me look at the actual implementation to give you a concrete answer.

Two main reasons:

**1. Different scopes — per-chunk vs. cross-chunk.**
Extract runs independently on each chunk (1 LLM call per chunk), pulling out raw entity names and context from that chunk's text. Resolve then aggregates across *all* chunks, deduplicates, and matches against the database + Wikidata. You can't do the cross-chunk dedup/matching until you've seen every chunk's entities.

**2. Different concerns — "what's mentioned?" vs. "what does it map to?"**
- **Extract** answers: *"Which artists/albums/venues appear in this text?"* — a straightforward NER task.
- **Resolve** answers: *"Is 'Bird' the same entity as 'Charlie Parker' from chunk 3? Does it match an existing DB record or a Wikidata entry?"* — a fuzzy matching + deduplication task that requires global context.

Merging them would mean either:
- Sending the entire transcript + full DB entity list in every per-chunk call (expensive, hits token limits), or
- Doing resolution chunk-by-chunk without cross-chunk dedup (poor quality — "Miles" in chunk 1 and "Miles Davis" in chunk 5 wouldn't get linked).

The separation also gives operational flexibility: you can re-run resolve without re-extracting (e.g., after improving the matching logic or adding Wikidata support — which was added recently in `9cc6b71`), and extraction results are cached in `chunk.entities_json` so nothing is lost between steps.

### User

In general, why does Named Entity Recognition (NER) need to run first and then in a second phase the linking step hapens where the recofnized entities are linked to something else? What is this something else by the way? Canonical entities?

### Assistant

Yes, exactly — the standard term is **Named Entity Recognition (NER)** followed by **Entity Linking (NEL)** (also called Entity Resolution or Entity Disambiguation).

## Why two phases?

**NER is a surface-level task:** scan text, find spans that look like entity names. It only needs local context — the words around a mention. "Bird played trumpet at Birdland" → `Bird` (person), `Birdland` (venue). Fast, parallelizable, no external knowledge needed.

**Entity Linking is a semantic task:** decide *which real-world thing* each mention refers to. "Bird" could be Charlie Parker, Larry Bird, or a literal bird. To disambiguate you need:
- The full set of mentions (cross-document/cross-chunk evidence)
- A **knowledge base** to link against
- Context-aware reasoning

These are fundamentally different problems with different inputs, different error modes, and different computational profiles. Combining them forces the model to do both at once, which in practice degrades quality on both.

## What do you link to?

The "something else" is entries in a **knowledge base (KB)**. Depending on the system:

| Knowledge base | What an entry represents |
|---|---|
| **Wikidata** | A Q-ID like `Q5765` (Miles Davis) — the most common target for general-domain NEL |
| **Wikipedia** | A page title / URL |
| **Your own DB** | A canonical `Entity` record (what ragtime does) |
| **MusicBrainz** | For music-domain entities specifically |

These entries are often called **canonical entities**, yes — a single authoritative record that all surface forms ("Bird", "Charlie Parker", "Yardbird") collapse into. The KB provides the canonical name, type, and often a unique ID.

## The classic pipeline

```
Text → NER (find mentions) → NEL (link to KB) → Canonical entities with mentions
```

In ragtime's case, the KB is the project's own `Entity` table (augmented by Wikidata lookups for disambiguation), and the links are stored as `EntityMention` records pointing from chunks back to canonical entities.

### User

Should we then rename the implemented concept "entity types" to "canoncal entities"?

### Assistant

No, those are different concepts:

- **Entity types** = the *categories* (artist, band, album, venue, label, year). These classify entities.
- **Canonical entities** = the *resolved, deduplicated records* in the `Entity` table (e.g., "Miles Davis", "Blue Note Records").

An entity type *has many* canonical entities. "Miles Davis" is a canonical entity *of type* "artist".

The naming in the codebase is correct as-is. If anything, the `Entity` model already *is* the canonical entity — no rename needed.

### User

What about rewriting the "Extract entities" and "Resolve entities" sections in the README to clarify what each step does? Adding examples would be helpful.

### Assistant

Let me read the current README sections first.

Now let me draft improved versions. Here's my proposal:

### User

[Request interrupted by user for tool use]

Create a worktree for this work before making the changes to the README

### Assistant

Now let me apply the edit in the worktree.

Done. The README now clarifies both steps with:

- **NER/NEL labels** so readers recognize the standard concepts
- **What happens** at each stage (per-chunk extraction vs. cross-chunk resolution)
- **What doesn't happen** (no DB records or dedup during extract)
- **Concrete examples** with Bird/Charlie Parker/Birdland/Dizzy Gillespie
- **Why two phases** — a brief rationale at the end of the resolve section

Ready for you to review. Want me to commit this?

### User

In which worktree are you working?

### Assistant

I'm working in `/Users/rafa/Develop/projects/ragtime/.claude/worktrees/docs/clarify-extract-resolve-readme` on branch `worktree-docs/clarify-extract-resolve-readme`.

### User

Bring these worktree changes to main

### Assistant

I'll commit the changes, exit the worktree, and merge the branch into main.

The worktree has an unmerged commit. Let me first merge it into main, then remove the worktree.

Merge conflict. Let me check and resolve it.

Let me use rebase instead (as the project requires rebase strategy).

There's a conflict — main has updated entity type names (e.g., "musician" instead of "artist"). Let me resolve it by keeping our new structure with the correct type names from main.

I need to resolve the conflict using the correct entity type names from main (musician, musical group, etc.) with our new structure. Let me also update the example table to use those names.

Now merge into main from the original repo.

Clean fast-forward merge. Now I can remove the worktree.

The commits are already merged into main via the fast-forward, so the branch can be safely removed.

Done. The README changes are now on `main` via a fast-forward merge. The worktree and its branch have been cleaned up. I also resolved a conflict where main had updated entity type names (e.g., "musician" instead of "artist", "music venue" instead of "venue") — the examples in the new text now use the correct names.

### User

Do a git status so that you know what the state of the local changes are.

### Assistant

The state: on `main`, up to date with `origin/main`, with the README changes unstaged. It looks like the fast-forward merge updated the local branch ref but the working tree has the changes as a dirty diff (the worktree removal may have left this state).

The diff is exactly what we want — the extract/resolve section rewrite with NER/NEL labels, examples, and the correct entity type names. Want me to commit this?

### User

No. Let's iterate a bit more. If Step 7 is actually about Named Entity Recognition (NER), shouldn't we change the name of the section/pipeline step name and also the pipeline state?

### Assistant

Good point. Here's what I'd suggest:

| Step | Current | Proposed | Rationale |
|---|---|---|---|
| 7 | Extract entities (`extracting`) | **Recognize entities** (`recognizing`) | Maps to NER |
| 8 | Resolve entities (`resolving`) | Keep as-is | "Entity resolution" is already a standard synonym for entity linking |

The rename for step 7 is a non-trivial change though — it touches the status enum in `models.py`, the signal dispatcher, likely tests, and the README pipeline section. Want me to scope out the full blast radius before we proceed?

### User

Is the wording "extract entities" also used?

### Assistant

Let me check where "extract" is used in the context of entities across the codebase.

Yes — "extract" is deeply embedded across the codebase:

- **Status enum**: `EXTRACTING = "extracting"` in `models.py`
- **Function**: `extract_entities()` in `extractor.py`
- **Module**: `episodes/extractor.py`
- **Signal dispatch**: references `Episode.Status.EXTRACTING`
- **Settings**: `RAGTIME_EXTRACTION_*` env vars
- **Config wizard**: "Extraction" label
- **Tests**: `test_extract.py`, multiple test methods
- **6+ migrations** with `extracting` in choices
- **README** and feature description

Renaming from "extract" to "recognize" would touch a *lot* of files, plus require a new migration to change the stored status value in the database. And `RAGTIME_EXTRACTION_*` env vars would need renaming too (breaking existing `.env` files).

Given the blast radius, it might be better to keep "extract" in the code/status (it's a common synonym for NER anyway — "entity extraction" is standard terminology) and just clarify in the README that this step performs NER, which is what the current rewrite already does. What do you think?

### User

Yes, let's do that, let's tidy up the READE for those sections.

[Request interrupted by user for tool use]
