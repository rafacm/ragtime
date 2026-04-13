# OTel + LangGraph Migration — Planning Session

**Date:** 2026-04-13

**Session ID:** 0f60528e-6b16-41a5-b9d0-13c277121673

## Summary

Planned the migration from Langfuse-specific observability to OpenTelemetry and from Django Q2 signal-based pipeline dispatch to LangGraph state graph orchestration. Discussed agent-native architecture goals, framework selection (LangGraph vs Pydantic AI vs Claude Agent SDK), and the role of Scott as the future top-level agent.

### User

If you review the architecture, we currently use Python to implement the ingestion pipeline and use agents via Pydantic AI to handle error cases. We want to move to an agent native architecture. Let's discuss and review the main changes needed to accomplish this:
- move to OpenTelemetry and use it as the back-bone for LLM observability and later for evaluation
- decide which agent framework to use instead of the current hard-coded Python pipeline

### Assistant

Explored the codebase in parallel with two agents: one investigating the pipeline architecture, signals, Pydantic AI agents, and observability; the other checking dependencies, env configuration, and the chat app status.

Presented the current state: 8 hard-coded steps orchestrated via Django signals + Django Q2, Pydantic AI used only for recovery, Langfuse observability via custom decorators, clean provider ABCs. Proposed discussion points on OTel migration (decouple instrumentation from backend) and agent framework selection (compared Pydantic AI, LangGraph, Claude Agent SDK).

Asked four questions: motivation for "agent native", whether the orchestrator should be an agent, OTel backend plans, and whether Scott is in scope.

### User

1. Because the chat "app" will be implement it as an agent itself and will need to interact with other parts of the application. Eventually we want users to provide a URL to Scott and for Scott to pass this URL to the "ingestion" orchestrator agent and update the user once all the phases have been done.

### Assistant

Identified the end-state architecture: Scott as top-level agent with tools (RAG retrieval + ingestion trigger), ingestion pipeline as an agent graph callable by Scott. This is fundamentally about composability — agents calling agents. Outlined requirements: tool registration, agent-to-agent delegation, long-running task awareness, state/checkpointing.

Asked three follow-up questions about orchestrator autonomy, OTel backend, and framework preference.

### User

1. Yes, it should have autonomy over step ordering/skipping.
2. We are evaluating alternatives like Sentry
3. We want to be able to run any needed server to support the framework locally. It should also have a UI so we can see/explore the agent graph and the executions

### Assistant

Concluded that LangGraph is the strongest fit: graph-based orchestration with conditional edges, checkpointing for resume, LangGraph Studio for local visualization, OTel native. Pydantic AI's graph support is newer and lacks comparable UI.

Launched a Plan agent to design the full migration. The agent produced a 5-phase plan: OTel migration, LangGraph pipeline, Studio setup, Scott agent, and cleanup. Each phase detailed specific files, graph topology, dependency changes, and configuration.

Wrote the plan to the plan file. User requested removing Phase 4 (Scott) to focus on OTel + LangGraph only. Trimmed the plan to 3 phases, folded cleanup into Phase 2. User approved the plan.
