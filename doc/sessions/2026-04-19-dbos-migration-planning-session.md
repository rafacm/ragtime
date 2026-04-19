# DBOS Migration Planning Session

**Date:** 2026-04-19

**Session ID:** 2d844f5c-cf29-47af-8019-7c0b4a3e2efa

## Summary

Planned the migration from Django Q2 to DBOS Transact for the episode ingestion pipeline. Explored the current architecture, researched DBOS integration patterns, and designed a migration approach that preserves the existing audit trail while replacing the signal-driven dispatch chain with a single durable workflow.

### User

Help me brainstorm whether to change the current implementation that uses D2 queues to use https://github.com/dbos-inc/dbos-transact-py

### Assistant

Explored the current Django Q2 usage across the codebase in parallel with researching DBOS Transact Python. Found that Q2 is used in only 2 production files (`signals.py` and `admin.py`) with 106 test mocks across 14 test files. The custom orchestration layer (ProcessingRun/ProcessingStep/PipelineEvent/recovery chain) is ~500 lines that DBOS would partially replace.

Presented a comparison: DBOS is a strong conceptual fit (the pipeline IS a durable workflow), but migration cost is non-trivial for a working system. Suggested trying DBOS on a new workflow first before migrating the existing pipeline.

### User

My plan is to migrate from a hard-coded pipeline to a fully agent based implementation using Pydantic AI where agents delegates to one another and there is an orchestrator agent that handles logic for the current pipeline. There is an existing Pydantic AI integration for DBOS that would add persistence to the agents. This I will tackle in a future PR but the migration to DBOS would be a step in that direction.

### Assistant

Agreed this makes sense as a stepping stone. Proposed scoping the DBOS migration as: replace Django Q2 dispatch + custom processing/recovery orchestration with DBOS workflows and steps, keeping the existing task functions as step implementations. Entered plan mode.

### User

yes

### Assistant

Entered plan mode. Launched three parallel Explore agents to thoroughly map:
1. Pipeline orchestration: signals.py, processing.py, recovery.py, apps.py, models.py, admin.py, settings.py — all Q2 touch points
2. Task function patterns: all 8 pipeline functions (scraper through embedder) — signatures, success/failure patterns, start_step/complete_step/fail_step usage
3. Tests and dependencies: all 106 async_task mocks, pyproject.toml, docker-compose, management commands

Then launched a Plan agent with comprehensive context to design the migration. Key design decisions:
- One DBOS workflow replaces signal chain (signals existed because Q2 has no workflow concept)
- ProcessingRun/ProcessingStep models stay as audit trail (complementary to DBOS checkpointing)
- Task functions unchanged — they don't raise after fail_step(), so workflow checks run status
- Recovery chain stays but resume_pipeline() uses DBOS.start_workflow instead of signal dispatch
- DBOS configured programmatically from Django DATABASES (no duplicate yaml config)

Read critical files to verify: task functions swallow exceptions after fail_step (workflow must check status), resume_pipeline creates new runs and sets status (needs DBOS workflow start), admin reprocess has scraping special-case (workflow handles uniformly).

Wrote final plan to plan file and exited plan mode.
