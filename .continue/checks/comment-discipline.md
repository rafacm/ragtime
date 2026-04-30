---
name: Comment Discipline
description: Comments must explain non-obvious WHY. No narration of the current task, no restating WHAT the code does, no rotting references to callers or issues.
---

# Comment Discipline

## Context

This codebase deliberately keeps comments rare. The repo's coding
guidelines (in `CLAUDE.md` / `AGENTS.md` and the wider Claude Code
defaults) state:

- Default to **no comments**. Add one only when the WHY is non-obvious:
  a hidden constraint, a subtle invariant, a workaround for a specific
  bug, behaviour that would surprise a reader.
- Don't explain WHAT the code does — well-named identifiers do that.
- Don't reference the current task, fix, or callers ("used by X",
  "added for the Y flow", "handles the case from issue #123") — those
  belong in the PR description and rot as the codebase evolves.
- No multi-paragraph docstrings or multi-line comment blocks. One short
  line is the cap.
- No `# removed code` / `# was: ...` tombstones. The git history is the
  history.

This is a judgment-heavy rule. A formatter cannot tell a useful WHY
comment apart from a noisy WHAT comment. That is what this check is for.

## What to Check

### 1. Reject WHAT comments

If the comment paraphrases what the next line obviously does, it should
go.

**BAD**

```python
# Loop over episodes and update status
for episode in episodes:
    episode.status = "ready"
    episode.save()
```

**GOOD** — drop the comment. The code is self-evident.

### 2. Reject task/PR/caller references

Comments referencing the moment of writing rot the fastest. They
mislead readers months later when callers move or issues close.

**BAD**

```python
# Added in PR #427 for the Wikidata enrichment workflow
# Used by chat/views.py
def hydrate_entities(...): ...
```

**GOOD** — drop both. If the function genuinely has a non-obvious
constraint (e.g. "must run inside a DBOS step because it relies on
checkpoint replay"), keep that single line.

### 3. Reject tombstones

Lines like `# removed: old impl`, `# was: foo()`, `# TODO: rewrite this`
without a tracked owner/date should be deleted, not added.

### 4. Keep load-bearing WHY comments

Some comments earn their keep. Don't flag these:

- A subtle invariant: `# keys must be sorted to avoid A→B / B→A deadlock`
- A workaround tied to a specific bug: `# Qdrant 1.10 returns float ids; cast to int`
- A surprising default: `# default 30 — Wikidata 429s above 1 req/s`
- An external contract: `# AG-UI requires the 'tool_use' chunk before 'text'`

The shape that signals "load-bearing": short, names a constraint or
external fact, would surprise a reader skimming the code.

### 5. Multi-line comment blocks

Module docstrings explaining architecture (like the header in
`episodes/vector_store.py`) are fine. Inline multi-paragraph blocks
above functions are not — collapse to one line or delete.

### 6. Empty / placeholder docstrings

`"""TODO: docstring"""` and `"""."""` are noise. Delete them.

## Key Files

Apply across the diff. Especially noisy areas historically:

- `episodes/resolver.py`
- `episodes/workflows.py`
- `chat/` view code
- New management commands under `*/management/commands/`

## Exclusions

- Module-level architectural docstrings that genuinely orient a reader
  to a non-trivial file (the header of `episodes/vector_store.py` is a
  fair example).
- Tests, where descriptive `# Given / # When / # Then` comments can
  improve readability — judgement call, lean permissive.
- Generated code / migrations.
