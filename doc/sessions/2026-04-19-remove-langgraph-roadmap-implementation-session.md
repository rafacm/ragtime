# Session: Remove LangGraph from the roadmap — Implementation

**Date:** 2026-04-19

**Session ID:** 34192517-1131-4eb0-bf50-d8b21a632c57

## Summary

Executed the approved plan to remove the "LangGraph pipeline" bullet from `README.md` and record the rationale in a dedicated feature doc. Added plan, feature, and session transcripts under `doc/`, plus a `CHANGELOG.md` entry. No code changes; documentation only.

## Conversation

### Assistant

Verified the repository was on `main` with a clean working tree and pulled the latest changes (already up to date). Created a new branch `docs/remove-langgraph-roadmap` off `main` per the project's branching policy.

Edited `README.md` to delete the "LangGraph pipeline" bullet from the "What's coming" section. The surrounding bullets (Embed step, Scott, AI evaluation) are unchanged. No replacement text was added to the README — the rationale lives only in the new feature document.

Created `doc/features/2026-04-19-remove-langgraph-roadmap.md` with the standard template (Problem, Rationale, Changes, Verification, Files modified). The rationale records three points:

1. Pydantic AI already covers the project's agentic needs — it powers the decoupled recovery layer and is sufficient for current and foreseeable workloads.
2. LangGraph's native observability and Studio tooling lean on LangSmith.
3. LangSmith is hosted-only and cannot be self-hosted, which conflicts with RAGtime's preference for locally runnable telemetry collectors (console, Jaeger, self-hosted Langfuse) standardized on OpenTelemetry.

Copied the approved plan to `doc/plans/2026-04-19-remove-langgraph-roadmap.md`.

Wrote the planning session transcript (`doc/sessions/2026-04-19-remove-langgraph-roadmap-planning-session.md`) with the real session UUID `34192517-1131-4eb0-bf50-d8b21a632c57`, captured from the active session log at `~/.claude/projects/-Users-rafa-Develop-projects-ragtime/`. User messages are verbatim; assistant prose summarizes the tool activity.

Added a `## 2026-04-19` section to `CHANGELOG.md` under a `### Changed` heading, cross-linking the plan, feature doc, and both session transcripts, following the Keep a Changelog conventions already used in the file.

Ran `uv run python manage.py test` to confirm the docs-only change did not regress anything.

Staged the documentation files and created a single commit on `docs/remove-langgraph-roadmap`. Pushed with `-u` and opened a pull request against `main` using the rebase strategy.

This transcript will be updated if PR review feedback produces follow-up changes.
