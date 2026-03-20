# Decoupled Recovery Architecture for Pipeline Failures

**Date:** 2026-03-18

## Problem

Pipeline steps (especially scraping and downloading) fail permanently with no recovery path. Admins must manually intervene via Django admin. The `NEEDS_REVIEW` status was a partial workaround for incomplete scraping but didn't address other failure modes (HTTP errors, timeouts, CloudFlare blocks).

## Changes

### Event Infrastructure

| Component | Description |
|---|---|
| `episodes/events.py` | New module: `StepCompletedEvent`, `StepFailureEvent` dataclasses, `classify_error()` for categorizing exceptions, `build_completion_event()` and `build_failure_event()` builders |
| `episodes/signals.py` | Added `step_completed` and `step_failed` custom Django signals |
| `episodes/processing.py` | `complete_step()` now builds `StepCompletedEvent`, persists `PipelineEvent`, sends `step_completed` signal. `fail_step()` accepts optional `exc` parameter; when provided, builds `StepFailureEvent`, persists `PipelineEvent`, sends `step_failed` signal |
| All 7 pipeline steps | Each except block now passes `exc=exc` to `fail_step()` |

### Error Classification

`classify_error(exc)` maps exceptions to structured categories:

| Exception type | Error category | HTTP status |
|---|---|---|
| `httpx.HTTPStatusError` | `http` | Response status code |
| `httpx.TimeoutException` | `timeout` | None |
| `subprocess.CalledProcessError/TimeoutExpired` | `subprocess` | None |
| `openai.APIError` | `provider` | None |
| `KeyError/ValueError/JSONDecodeError` | `validation` | None |
| Everything else | `system` | None |

### Recovery Layer

| Component | Description |
|---|---|
| `episodes/recovery.py` | `RecoveryStrategy` ABC with `can_handle()` and `attempt()` methods. `RecoveryResult` dataclass (success, message, should_escalate). Two built-in strategies + dispatcher |
| `AgentStrategy` | Stub — handles scraping/downloading when `RAGTIME_RECOVERY_AGENT_ENABLED=True`, always escalates. Ready for Phase 4 implementation |
| `HumanEscalationStrategy` | Final fallback — creates `AWAITING_HUMAN` recovery attempt. Always handles, never escalates |
| `handle_step_failure()` | Signal handler connected to `step_failed`. Walks the configured chain, creates `RecoveryAttempt` records. Hard ceiling of 5 attempts per (episode, step) |

### New Models

**PipelineEvent** — audit trail for all pipeline step outcomes:
- `episode` FK, `processing_step` FK, `event_type` (completed/failed)
- `step_name`, `error_type`, `error_message`, `http_status`, `exception_class`
- `context` JSONField (duration for successes, cached_data + attempt_number for failures)

**RecoveryAttempt** — tracks recovery strategy execution:
- `episode` FK, `pipeline_event` FK, `strategy` (agent/human)
- `status` (attempted/awaiting_human/resolved), `success`, `message`
- `resolved_at`, `resolved_by` (for human resolution tracking)

### NEEDS_REVIEW Removal

- Removed `NEEDS_REVIEW` from `Episode.Status` choices
- Incomplete metadata after scraping now sets `FAILED` status with descriptive error message
- Recovery chain handles escalation to human
- Admin reprocess action resolves `AWAITING_HUMAN` records when reprocessing

### Admin Integration

- `PipelineEventInline` on EpisodeAdmin — colour-coded success/failure events
- `PipelineEventAdmin` — standalone list view with filters (event_type, step_name, error_type)
- `RecoveryAttemptInline` on EpisodeAdmin — recovery history
- `RecoveryAttemptAdmin` with "Needs Human Action" list filter
- Reprocess action now resolves AWAITING_HUMAN records before reprocessing

### Observability

- Added `setup()` function to `observability.py` — eagerly initializes Langfuse TracerProvider at startup
- Called from `EpisodesConfig.ready()`

### Configuration

| Setting | Default | Description |
|---|---|---|
| `RAGTIME_RECOVERY_CHAIN` | `["agent", "human"]` | Ordered list of recovery strategies |
| `RAGTIME_RECOVERY_AGENT_ENABLED` | `false` | Feature flag for AI agent recovery |

## Key Parameters

| Parameter | Value | Rationale |
|---|---|---|
| `MAX_RECOVERY_ATTEMPTS` | 5 | Hard ceiling to prevent infinite loops |
| Recovery chain order | agent → human | Agent tries first (when enabled), human is final fallback |

## Verification

1. `uv run python manage.py test` — 186 tests pass (162 existing + 24 new)
2. New tests cover: error classification (8 cases), event emission (3 cases), recovery strategies (5 cases), recovery chain (2 cases), dispatcher (3 cases), end-to-end integration (1 case)
3. Admin verification: PipelineEvent and RecoveryAttempt inlines visible on episode detail, standalone list views with filters work, reprocess resolves AWAITING_HUMAN records

## Files Modified

| File | Change |
|---|---|
| `episodes/events.py` | **New.** Event dataclasses, `classify_error()`, event builders |
| `episodes/recovery.py` | **New.** Strategy ABC, two strategies, dispatcher |
| `episodes/models.py` | Removed NEEDS_REVIEW status. Added PipelineEvent and RecoveryAttempt models |
| `episodes/processing.py` | `complete_step()` emits events. `fail_step()` accepts `exc`, emits events |
| `episodes/signals.py` | Added `step_completed` and `step_failed` custom signals |
| `episodes/apps.py` | Connected recovery handler, added observability setup |
| `episodes/observability.py` | Added `setup()` for eager TracerProvider init |
| `episodes/admin.py` | PipelineEvent/RecoveryAttempt inlines and admin views, removed NEEDS_REVIEW logic |
| `episodes/scraper.py` | Incomplete metadata now FAILED (not NEEDS_REVIEW), pass `exc=exc` |
| `episodes/downloader.py` | Pass `exc=exc` to `fail_step()` |
| `episodes/transcriber.py` | Pass `exc=exc` to `fail_step()` |
| `episodes/summarizer.py` | Pass `exc=exc` to `fail_step()` |
| `episodes/chunker.py` | Pass `exc=exc` to `fail_step()` |
| `episodes/extractor.py` | Pass `exc=exc` to `fail_step()` |
| `episodes/resolver.py` | Pass `exc=exc` to `fail_step()` |
| `episodes/migrations/0018_*` | Migration: alter Episode.status, create PipelineEvent, create RecoveryAttempt |
| `ragtime/settings.py` | Added `RAGTIME_RECOVERY_CHAIN` and `RAGTIME_RECOVERY_AGENT_ENABLED` |
| `.env.sample` | Added `RAGTIME_RECOVERY_AGENT_ENABLED` |
| `core/management/commands/_configure_helpers.py` | Added Recovery system to wizard |
| `episodes/tests/test_events.py` | **New.** Tests for classify_error and event emission |
| `episodes/tests/test_recovery.py` | **New.** Tests for strategies, chain, dispatcher, integration |
| `episodes/tests/test_models.py` | Updated: NEEDS_REVIEW → DOWNLOADING in status test |
| `episodes/tests/test_scraper.py` | Updated: NEEDS_REVIEW → FAILED in incomplete extraction test |
| `episodes/tests/test_admin.py` | Updated: NEEDS_REVIEW → FAILED in admin tests |
| `core/tests/test_configure.py` | Updated: added Recovery prompt to wizard mock inputs |
