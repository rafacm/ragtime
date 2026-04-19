# Remove LangGraph from the roadmap

**Date:** 2026-04-19

## Problem

`README.md` listed a **LangGraph pipeline** as an upcoming feature in the "What's coming" section — a planned migration of the Django Q2 signal-based pipeline to a LangGraph `StateGraph`, along with LangGraph Studio for visualization. The project will no longer pursue this direction, so the bullet advertised a feature that isn't coming.

## Rationale

We are not introducing LangGraph for three reasons:

1. **Pydantic AI already covers the project's agentic needs.** [Pydantic AI](https://ai.pydantic.dev/) powers the decoupled [recovery layer](../features/2026-03-18-decoupled-recovery-architecture.md) and is sufficient for RAGtime's current and foreseeable agent workloads. Adding a second agent/orchestration framework alongside it would be redundant.
2. **LangGraph's observability story leans on LangSmith.** LangGraph's native tracing integration and its Studio visualization tooling are tightly coupled to [LangSmith](https://smith.langchain.com/). Adopting LangGraph would effectively mean adopting LangSmith to get meaningful observability.
3. **LangSmith is hosted-only and cannot be self-hosted.** This conflicts with RAGtime's preference for locally runnable telemetry collectors. The project already standardized on [OpenTelemetry](../features/2026-04-15-opentelemetry-telemetry.md) with three collector options — console, self-hosted [Jaeger](https://www.jaegertracing.io/), and self-hosted [Langfuse](https://langfuse.com) — all of which run offline on a laptop.

## Changes

- **`README.md`** — removed the "LangGraph pipeline" bullet from the "What's coming" section. The remaining bullets (Embed step, Scott, AI evaluation) are unchanged. No replacement text was added to the README — the rationale lives here in the feature doc.

## Verification

1. `grep -n 'LangGraph\|langgraph' README.md doc/README.md CHANGELOG.md` → no matches.
2. Render `README.md` on GitHub — "What's coming" now lists only Embed step, Scott, and AI evaluation.
3. `uv run python manage.py test` — docs-only change; tests should pass unchanged.

## Files modified

| File | Change |
|---|---|
| `README.md` | Removed the "LangGraph pipeline" bullet from "What's coming". |
| `CHANGELOG.md` | Added 2026-04-19 `### Changed` entry. |
| `doc/plans/2026-04-19-remove-langgraph-roadmap.md` | **New** — plan document. |
| `doc/features/2026-04-19-remove-langgraph-roadmap.md` | **New** — this file. |
| `doc/sessions/2026-04-19-remove-langgraph-roadmap-planning-session.md` | **New** — planning session transcript. |
| `doc/sessions/2026-04-19-remove-langgraph-roadmap-implementation-session.md` | **New** — implementation session transcript. |
