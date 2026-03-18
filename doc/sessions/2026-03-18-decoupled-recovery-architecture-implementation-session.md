# Session: Decoupled Recovery Architecture — Implementation

**Session ID:** (current implementation session)
**Date:** 2026-03-18

## Summary

Implemented Phases 1-3 of the Decoupled Recovery Architecture plan: structured pipeline events, recovery layer with strategy chain, and admin integration. Removed the NEEDS_REVIEW status in favor of FAILED + recovery escalation.

## Conversation

### User
Asked to implement the Decoupled Recovery Architecture plan, covering event infrastructure, recovery layer, and admin integration (Phases 1-3).

### Assistant
Read all key files to understand the current codebase before making changes:
- `episodes/models.py` — Episode.Status, ProcessingStep, ProcessingRun
- `episodes/processing.py` — complete_step(), fail_step()
- `episodes/signals.py` — queue_next_step signal handler
- `episodes/apps.py` — EpisodesConfig.ready()
- `episodes/observability.py` — Langfuse tracing layer
- `episodes/admin.py` — all admin views
- All 7 pipeline steps (scraper, downloader, transcriber, summarizer, chunker, extractor, resolver)
- Settings, .env.sample, pyproject.toml, configure helpers
- All test files referencing NEEDS_REVIEW

Created feature branch `feature/decoupled-recovery-architecture` from main.

#### Phase 1: Event Infrastructure

1. Created `episodes/events.py` with:
   - `StepCompletedEvent` and `StepFailureEvent` frozen dataclasses
   - `classify_error()` mapping exceptions to (error_type, http_status) tuples
   - `build_completion_event()` and `build_failure_event()` builders

2. Updated `episodes/models.py`:
   - Removed `NEEDS_REVIEW` from Episode.Status choices
   - Added `PipelineEvent` model (episode FK, processing_step FK, event_type, error fields, context JSONField)
   - Added `RecoveryAttempt` model (episode FK, pipeline_event FK, strategy, status, success, resolved_at/by)

3. Updated `episodes/signals.py`:
   - Added `step_completed` and `step_failed` custom Django signals

4. Rewrote `episodes/processing.py`:
   - `complete_step()` now builds StepCompletedEvent, creates PipelineEvent record, sends step_completed signal
   - `fail_step()` now accepts optional `exc` parameter; when provided, builds StepFailureEvent, creates PipelineEvent record, sends step_failed signal with pipeline_event kwarg

5. Updated all 7 pipeline steps to pass `exc=exc` to `fail_step()` (one-line change each)

6. Updated `episodes/scraper.py`:
   - Incomplete metadata now sets FAILED status with "Incomplete metadata: missing required fields" error message instead of NEEDS_REVIEW
   - Added `error_message` to update_fields in the metadata save call

#### Phase 2: Recovery Layer

1. Created `episodes/recovery.py`:
   - `RecoveryResult` dataclass with success/message/should_escalate
   - `RecoveryStrategy` ABC with can_handle() and attempt() methods
   - `AgentStrategy` — stub, handles scraping/downloading when RAGTIME_RECOVERY_AGENT_ENABLED=True, always returns should_escalate=True
   - `HumanEscalationStrategy` — final fallback, creates AWAITING_HUMAN status, never escalates
   - `STRATEGY_REGISTRY` for name->class mapping
   - `get_recovery_chain()` builds chain from RAGTIME_RECOVERY_CHAIN setting
   - `handle_step_failure()` signal handler with MAX_RECOVERY_ATTEMPTS=5 ceiling

2. Updated `episodes/apps.py`:
   - Connected handle_step_failure to step_failed signal in ready()
   - Added observability.setup() call

3. Added `setup()` to `episodes/observability.py` for eager TracerProvider init

4. Added to `ragtime/settings.py`:
   - `RAGTIME_RECOVERY_CHAIN = ["agent", "human"]`
   - `RAGTIME_RECOVERY_AGENT_ENABLED` from env

5. Updated `.env.sample` with `RAGTIME_RECOVERY_AGENT_ENABLED`

6. Updated `core/management/commands/_configure_helpers.py` with Recovery system

#### Phase 3: Admin Integration

1. Updated `episodes/admin.py`:
   - Added `PipelineEventInlineForEpisode` with colour-coded event_type display
   - Added `RecoveryAttemptInlineForEpisode` showing recovery history
   - Added `PipelineEventAdmin` standalone view with filters (event_type, step_name, error_type)
   - Added `RecoveryAttemptAdmin` with NeedsHumanActionFilter
   - Updated EpisodeAdmin.get_inlines() to include new inlines
   - Removed NEEDS_REVIEW-specific readonly field logic
   - Reprocess action now resolves AWAITING_HUMAN records

#### Test Fixes

Updated existing tests for NEEDS_REVIEW removal:
- `test_models.py` — changed NEEDS_REVIEW assertion to DOWNLOADING
- `test_scraper.py` — incomplete extraction now expects FAILED, reprocess tests use FAILED status
- `test_admin.py` — admin tests use FAILED status, metadata test checks readonly
- `test_configure.py` — added Recovery agent_enabled prompt to mock inputs

#### New Tests

Created `test_events.py` (11 tests):
- classify_error for HTTP, timeout, subprocess, subprocess timeout, key/value/JSON errors, system errors
- PipelineEvent emission from complete_step and fail_step

Created `test_recovery.py` (13 tests):
- AgentStrategy: disabled by default, handles scraping/downloading, doesn't handle transcribing, stub escalates
- HumanEscalationStrategy: always handles, doesn't escalate
- Recovery chain configuration
- Dispatcher: creates AWAITING_HUMAN, agent escalates to human, max attempts prevention
- Integration: fail_step with exc triggers full recovery chain

All 186 tests pass.
