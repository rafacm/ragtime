# Decoupled Recovery Architecture for Pipeline Failures

**Date:** 2026-03-18

## Context

Steps 2 (scraping) and 3 (downloading) in the RAGtime pipeline sometimes fail — audio URLs not found in HTML, downloads blocked by 403/CloudFlare. Currently failures are permanent (`max_attempts: 1`), requiring manual admin intervention.

The processing pipeline is one concern; how errors are fixed is a separate concern. This plan introduces a **decoupled recovery layer** where:
- The **pipeline** emits rich failure events with structured context
- A **recovery layer** subscribes to failures and walks an escalation chain: agent → human
- The **agent** (Pydantic AI + Playwright) is just one pluggable strategy, not hardwired into the pipeline

## Architecture: Three Layers

```
┌─────────────────────────────────────────────────────┐
│  Pipeline Layer (existing)                          │
│  scraper → downloader → transcriber → ...           │
│  Emits step_completed / step_failed signals         │
└──────────────────────┬──────────────────────────────┘
                       │ signals
            ┌──────────┴──────────┐
            ▼                     ▼
   step_completed           step_failed
   (logged, visible         (triggers recovery)
    in admin)                     │
                                  ▼
┌─────────────────────────────────────────────────────┐
│  Recovery Layer (new: episodes/recovery.py)          │
│  Walks configured chain: agent → human              │
│  Each strategy: can_handle(event)? → attempt(event) │
│  Records every attempt in RecoveryAttempt model      │
└──────────────────────┬──────────────────────────────┘
                       │
               ┌───────┴───────┐
               ▼               ▼
         AgentStrategy    HumanEscalation
         (Pydantic AI     (create task,
          + Playwright)    notify admin)
```

## Implementation Phases

### Phase 1: Event infrastructure (this PR)
- `events.py` with StepCompletedEvent, StepFailureEvent, classify_error()
- PipelineEvent and RecoveryAttempt models (migration)
- Remove NEEDS_REVIEW from Episode.Status choices
- step_completed and step_failed custom signals
- Modify complete_step() / fail_step() to emit events
- Pass exc=exc in each pipeline step's except block

### Phase 2: Recovery layer (this PR)
- recovery.py with strategy ABC, dispatcher, two strategies
- HumanEscalationStrategy creating AWAITING_HUMAN records
- Stub AgentStrategy (always escalates, behind feature flag)
- Wire signal handler in apps.py
- Recovery settings in settings.py / .env.sample

### Phase 3: Admin integration (this PR)
- PipelineEventInline on EpisodeAdmin
- PipelineEventAdmin standalone view with filters
- RecoveryAttemptInline on EpisodeAdmin
- "Needs Human Action" list filter
- Reprocess action resolves AWAITING_HUMAN records

### Phase 4: Agent strategy (future PR)
- episodes/agents/ package
- Pydantic AI agent with Playwright browser tools
- Agent.instrument_all() for Langfuse tracing
