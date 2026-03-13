# Feature: Multi-session transcript format

## Problem

The session transcript guidelines in `AGENTS.md` assumed each feature corresponds to a single Claude Code session. In practice, features span multiple sessions — typically a planning session followed by one or more implementation sessions (the context is cleared between plan approval and implementation). The previous instructions did not capture session IDs or the assistant's reasoning steps, making transcripts less useful for understanding how decisions were made.

## Changes

Updated the session transcript paragraph in `AGENTS.md` to:

- **Multi-session coverage** — A transcript file covers all sessions for a feature, not just one.
- **Session IDs** — A `## Sessions` section lists every Claude Code session ID that contributed.
- **Reasoning detail** — Transcripts must include the assistant's reasoning steps (what it explored, alternatives considered, rationale for chosen approach).
- **Session separation** — When multiple sessions are involved, each is separated with a `## Session N` heading that includes the session ID.

## Key parameters

None — this is a documentation-only change.

## Verification

Review `AGENTS.md` and confirm the session transcript section reflects the new multi-session format with session IDs and reasoning requirements.

## Files modified

| File | Change |
|------|--------|
| `AGENTS.md` | Replaced single-paragraph session transcript instructions with structured multi-session format |
