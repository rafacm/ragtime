# Remove LangGraph from the roadmap

**Date:** 2026-04-19

## Context

`README.md` currently lists a **LangGraph pipeline** as an upcoming feature under "What's coming" (line 49). The project will no longer introduce LangGraph, so the bullet is inaccurate and should be deleted.

Separately, the rationale for dropping LangGraph is worth recording — but only in the feature documentation for this change, not in `README.md` itself. Dated session transcripts and plan documents that mention LangGraph in `doc/sessions/` and `doc/plans/` are archival and will be left alone.

## Rationale (lives in the feature doc, not the README)

LangGraph was considered as a pipeline orchestration layer and observability accelerator. We are not introducing it because:

1. **Pydantic AI already covers our agentic needs.** [Pydantic AI](https://ai.pydantic.dev/) powers the recovery layer (see `2026-03-18-decoupled-recovery-architecture.md`) and is sufficient for the project's current and foreseeable agent workloads.
2. **LangGraph brings LangSmith for observability.** LangGraph's native tracing and its Studio visualization are tightly coupled to [LangSmith](https://smith.langchain.com/).
3. **LangSmith is hosted-only.** It cannot be self-hosted, which conflicts with RAGtime's preference for locally runnable telemetry collectors — today we already support console, [Jaeger](https://www.jaegertracing.io/), and self-hosted [Langfuse](https://langfuse.com) via OpenTelemetry.

## Changes

1. **`README.md`** — delete the "LangGraph pipeline" bullet under "What's coming". Leave the surrounding Embed/Scott/AI-evaluation bullets as-is. No replacement text in the README.
2. **`doc/features/2026-04-19-remove-langgraph-roadmap.md`** — new feature doc following the standard template (Problem, Changes, Verification, Files modified). Contains the three-point rationale above.
3. **`doc/plans/2026-04-19-remove-langgraph-roadmap.md`** — this plan.
4. **`doc/sessions/2026-04-19-remove-langgraph-roadmap-planning-session.md`** — planning session transcript.
5. **`doc/sessions/2026-04-19-remove-langgraph-roadmap-implementation-session.md`** — implementation session transcript.
6. **`CHANGELOG.md`** — add a `## 2026-04-19` section with a `### Changed` entry linking to the plan, feature doc, and both session transcripts.
7. **Branching** — create a dedicated branch off `main` (`docs/remove-langgraph-roadmap`), open a PR using the rebase strategy.

## Files intentionally left alone

Historical records; scrubbing them would rewrite the archive:

- `doc/plans/2026-04-15-opentelemetry-telemetry.md`
- `doc/sessions/2026-04-15-opentelemetry-telemetry-planning-session.md`
- `doc/sessions/2026-04-15-opentelemetry-telemetry-implementation-session.md`
- `doc/sessions/2026-03-18-decoupled-recovery-architecture-planning-session.md`
- `doc/sessions/2026-03-18-decoupled-recovery-architecture-implementation-session.md`

## Verification

1. `grep -n 'LangGraph\|langgraph' README.md doc/README.md CHANGELOG.md` → no matches.
2. `grep -rn 'LangGraph\|langgraph' doc/features/ doc/plans/` → only matches in the new 2026-04-19 feature/plan docs (rationale) and the archival 2026-04-15 plan.
3. Render `README.md` and confirm "What's coming" now contains only Embed step, Scott, and AI evaluation.
4. `uv run python manage.py test` — docs-only change, but run it once to confirm nothing else regressed.
5. PR review: confirm the feature doc explains the rationale clearly and the CHANGELOG entry cross-links all four new doc files.
