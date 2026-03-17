# Session: Clarify Extract and Resolve README — Planning

**Session ID:** 3ce31107-6e3f-4071-9b59-a054e2a236a3
**Date:** 2026-03-17

## Summary

Planned a rewrite of README pipeline steps 7 (Extract entities) and 8 (Resolve entities) to introduce NER/NEL terminology, add concrete examples, and explain the two-phase design rationale. Considered renaming "extract" to "recognize" across the codebase but decided against it due to large blast radius (code, migrations, env vars, tests).

## Conversation

### User
Asked to review and improve the README sections for steps 7 and 8 of the pipeline.

### Assistant
Read the current README sections. Proposed a rewrite that:
- Adds NER/NEL labels as bold subtitles
- Breaks dense paragraphs into structured sections
- Adds example tables for both steps (extraction from sample text, surface form collapse during resolution)
- Adds a rationale paragraph for the two-phase design
- Moves `Chunk.entities_json` mention earlier in step 7

Applied the changes to the working tree.

### User
Asked whether we should rename "extract" to "recognize" in code to align with NER terminology.

### Assistant
Analyzed the blast radius: the term "extract" appears in status values (`extracting`), model fields, provider classes, signal handlers, management commands, tests, and env vars. Renaming would touch 20+ files, require a migration, and break the `RAGTIME_EXTRACTION_*` env var prefix. Recommended keeping "extract" in code and using the NER/NEL labels only in documentation.

### User
Agreed. Asked to proceed with the documentation-only approach.

### Assistant
Created the implementation plan and saved it to `doc/plans/clarify-extract-resolve-readme.md`.
