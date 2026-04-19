# Session: Remove LangGraph from the roadmap — Planning

**Date:** 2026-04-19

**Session ID:** 34192517-1131-4eb0-bf50-d8b21a632c57

## Summary

Planned the removal of the "LangGraph pipeline" bullet from the "What's coming" section of `README.md` and the creation of a feature document that records *why* LangGraph is no longer on the roadmap. Dated historical session transcripts and plan documents that mention LangGraph are left untouched as archival records.

## Conversation

### User

Let's remove the "LangGraph" information from the documentation since we will not be introducing it in the project.

### Assistant

Searched the repository for `LangGraph|langgraph` across all documentation and code. Found 6 files with matches:

- `README.md` — one active "What's coming" bullet (line 49) advertising a LangGraph pipeline migration.
- `doc/plans/2026-04-15-opentelemetry-telemetry.md` — historical plan referencing the decision to skip LangGraph during the OpenTelemetry work.
- `doc/sessions/2026-04-15-opentelemetry-telemetry-planning-session.md` and the matching implementation session — transcripts of the OpenTelemetry planning/implementation work.
- `doc/sessions/2026-03-18-decoupled-recovery-architecture-planning-session.md` and the matching implementation session — transcripts recording the framework evaluation that rejected LangGraph in favour of Pydantic AI.

Confirmed `doc/README.md` and `CHANGELOG.md` have no LangGraph references.

Since five of the six files are dated archival records, asked the user whether to remove only the active README bullet or to scrub the historical transcripts/plans as well. Offered "README.md only" as the recommended option.

### User

Selected **README.md only**.

### Assistant

Drafted a plan that removes the README bullet, leaves all dated history intact, and documents the removal with a verification step. Called `ExitPlanMode`.

### User

Let's also add the reason for not introducing LangGraph. Help me formulate it: the reason is that the project already uses PydanticAI which is enough for this project's requirements. Introducing LangGraph also required introducing LangSmith for LLM obserbability and LangSmith is a hosted solution an cannot be run locally.

### Assistant

Proposed two questions — where the rationale should live (README subsection vs. inline note vs. `doc/README.md`) and how strongly to phrase the LangSmith coupling claim ("leans on" vs. "requires"). Noted that LangGraph technically works without LangSmith but its native tracing and Studio tooling are tightly coupled to it.

### User

The user deferred the two questions and asked to clarify instead.

### Assistant

Asked what needed clarification about placement, wording, or the LangSmith-coupling framing.

### User

We do not need this info in the README. We just need to add it to this feature documentation.

### Assistant

Updated the plan to remove the README bullet with no replacement text, and to record the rationale only in a new feature doc (`doc/features/2026-04-19-remove-langgraph-roadmap.md`). Formalized the three-point rationale:

1. Pydantic AI already covers the project's agentic needs (used in the recovery layer).
2. LangGraph's native observability and Studio tooling lean on LangSmith.
3. LangSmith is hosted-only and cannot be self-hosted, conflicting with the project's preference for locally runnable telemetry (console, Jaeger, self-hosted Langfuse via OpenTelemetry).

Added the standard documentation artefacts to the plan (feature doc, plan copy, planning + implementation session transcripts, CHANGELOG entry) and the branching requirement (`docs/remove-langgraph-roadmap`, rebase-merge PR). Called `ExitPlanMode`.

### User

Approved the plan.
