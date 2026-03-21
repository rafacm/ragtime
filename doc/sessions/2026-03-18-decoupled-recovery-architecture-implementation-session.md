# Session: Decoupled Recovery Architecture — Implementation

**Date:** 2026-03-18
**Session ID:** e024308c-acb7-4da0-86d2-783f84f07b60

## Summary

Implemented Phases 1-3 of the Decoupled Recovery Architecture plan: structured pipeline events, recovery layer with strategy chain, and admin integration. Removed the NEEDS_REVIEW status in favor of FAILED + recovery escalation.

## Conversation

### User

Implement the following plan:

# Decoupled Recovery Architecture for Pipeline Failures

## Context

Steps 2 (scraping) and 3 (downloading) in the RAGtime pipeline sometimes fail — audio URLs not found in HTML, downloads blocked by 403/CloudFlare. Currently failures are permanent (`max_attempts: 1`), requiring manual admin intervention.

The processing pipeline is one concern; how errors are fixed is a separate concern. This plan introduces a **decoupled recovery layer** where:
- The **pipeline** emits rich failure events with structured context
- A **recovery layer** subscribes to failures and walks an escalation chain: agent → human
- The **agent** (Pydantic AI + Playwright) is just one pluggable strategy, not hardwired into the pipeline

---

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

---

## 1. Structured Pipeline Events

**New module: `episodes/events.py`**

```python
@dataclasses.dataclass(frozen=True)
class StepCompletedEvent:
    episode_id: int
    step_name: str                  # "scraping", "downloading", etc.
    processing_run_id: int
    processing_step_id: int
    duration_seconds: float         # how long the step took
    timestamp: datetime

@dataclasses.dataclass(frozen=True)
class StepFailureEvent:
    episode_id: int
    step_name: str                  # "scraping", "downloading", etc.
    processing_run_id: int
    processing_step_id: int
    error_type: str                 # "http", "timeout", "provider", "validation", "system"
    error_message: str
    http_status: int | None
    exception_class: str            # "httpx.HTTPStatusError"
    attempt_number: int             # computed from RecoveryAttempt count
    cached_data: dict               # intermediate data (e.g. scraped_html)
    timestamp: datetime
```

**Error classification** (`classify_error(exc)` in same module):
- `httpx.HTTPStatusError` → `("http", status_code)`
- `httpx.TimeoutException` → `("timeout", None)`
- `subprocess.CalledProcessError` / `subprocess.TimeoutExpired` → `("subprocess", None)`
- `openai.APIError` → `("provider", None)`
- `KeyError`/`ValueError`/`JSONDecodeError` → `("validation", None)`
- Everything else → `("system", None)`

---

## 2. Custom Django Signals

**In `episodes/signals.py`:**

```python
step_completed = django.dispatch.Signal()  # sends: event=StepCompletedEvent
step_failed = django.dispatch.Signal()     # sends: event=StepFailureEvent
```

**Integration points in `episodes/processing.py`:**

`complete_step()` — build `StepCompletedEvent` and send `step_completed`:
```python
def complete_step(episode, step_name):
    # ... existing logic to mark step as COMPLETED ...
    event = build_completion_event(episode, step_name, run, step_obj)
    step_completed.send(sender=Episode, event=event)
```

`fail_step()` — accept raw exception, build `StepFailureEvent`, send `step_failed`:
```python
def fail_step(episode, step_name, error="", exc=None):
    # ... existing logic to mark step/run as FAILED ...
    if exc is not None:
        event = build_failure_event(episode, step_name, run, step_obj, exc)
        step_failed.send(sender=Episode, event=event)
```

Each pipeline step's except block: add `exc=exc` to `fail_step()` call (one-line change each).

---

## 3. Recovery Layer

**New module: `episodes/recovery.py`**

### Strategy interface

```python
class RecoveryStrategy(ABC):
    name: str
    def can_handle(self, event: StepFailureEvent) -> bool: ...
    def attempt(self, event: StepFailureEvent) -> RecoveryResult: ...

@dataclasses.dataclass
class RecoveryResult:
    success: bool
    message: str
    should_escalate: bool  # if True, try next strategy in chain
```

### Two built-in strategies

| Strategy | When it fires | What it does |
|---|---|---|
| **AgentStrategy** | Scraping/download errors, `RAGTIME_RECOVERY_AGENT_ENABLED=True` | Runs Pydantic AI agent with Playwright tools. Initially a stub returning `should_escalate=True` |
| **HumanEscalationStrategy** | Always (final fallback) | Creates `AWAITING_HUMAN` recovery attempt. End of chain. |

### Dispatcher (signal handler)

```python
def handle_step_failure(sender, event, **kwargs):
    chain = get_recovery_chain()  # from settings
    for strategy in chain:
        if strategy.can_handle(event):
            result = strategy.attempt(event)
            RecoveryAttempt.objects.create(...)
            if result.success or not result.should_escalate:
                return
```

Connected in `episodes/apps.py:ready()`.

### Configuration (Django settings)

```python
RAGTIME_RECOVERY_CHAIN = ["agent", "human"]
RAGTIME_RECOVERY_AGENT_ENABLED = False  # feature flag
```

---

## 4. Event & Recovery Tracking

### Pipeline events (new model: `PipelineEvent`)

Stores both success and failure events for admin visibility and audit.

| Field | Type | Purpose |
|---|---|---|
| `episode` | FK → Episode | Which episode |
| `processing_step` | FK → ProcessingStep | Which step |
| `event_type` | CharField (completed/failed) | Success or failure |
| `step_name` | CharField | "scraping", "downloading", etc. |
| `error_type` | CharField (nullable) | "http", "timeout", etc. (failures only) |
| `error_message` | TextField | Human-readable error (failures only) |
| `http_status` | IntegerField (nullable) | HTTP status code (failures only) |
| `exception_class` | CharField (nullable) | e.g. "httpx.HTTPStatusError" |
| `context` | JSONField | Full event data (cached_data for failures, duration for successes) |
| `created_at` | DateTimeField | When the event occurred |

### Recovery attempts (new model: `RecoveryAttempt`)

| Field | Type | Purpose |
|---|---|---|
| `episode` | FK → Episode | Which episode |
| `pipeline_event` | FK → PipelineEvent | The failure event that triggered recovery |
| `strategy` | CharField (agent/human) | Which strategy was tried |
| `status` | CharField (attempted/awaiting_human/resolved) | Current state |
| `success` | BooleanField | Did the attempt succeed? |
| `message` | TextField | What happened |
| `created_at` | DateTimeField | When attempted |
| `resolved_at` | DateTimeField (nullable) | When resolved |
| `resolved_by` | CharField | "agent", "human:admin" |

No need for `error_context` on `ProcessingStep` — the `PipelineEvent` model holds all structured data. No backwards compatibility concerns (pre-v1).

**Infinite loop prevention:**
1. `attempt_number` in `StepFailureEvent` computed from `RecoveryAttempt.count()` per (episode, step_name)
2. Hard ceiling (e.g., 5 total attempts per episode+step) — escalates to human regardless

---

## 5. Admin Integration

### Pipeline events in admin
- `PipelineEventInline` on `EpisodeAdmin` — shows all events (success + failure) for an episode
- `PipelineEventAdmin` — standalone list view with filters by `event_type`, `step_name`, `error_type`
- Colour-coded: green for completed, red for failed

### Recovery attempts in admin
- `RecoveryAttemptInline` on `EpisodeAdmin` — shows recovery history
- "Needs Human Action" list filter: queries `RecoveryAttempt.objects.filter(status="awaiting_human")`

### Human-in-the-Loop

**Current state**: `NEEDS_REVIEW` status makes fields editable in admin. Manual reprocess action.

**New approach**: Remove `NEEDS_REVIEW` status entirely (no backwards compat needed, pre-v1). Instead:
- `HumanEscalationStrategy` creates `RecoveryAttempt(status=AWAITING_HUMAN)`
- Episode stays `FAILED`
- Admin reprocess action resolves `AWAITING_HUMAN` records
- Management command `pending_reviews` for CLI visibility

---

## 6. Technology Choices

### Agentic framework: Pydantic AI

| Criterion | Assessment |
|---|---|
| **Fit** | Tools are typed Python functions with dependency injection. `agent.run_sync()` works in Django Q2 tasks. |
| **Model flexibility** | OpenAI, Anthropic, Gemini, Groq, Mistral. Follows existing `RAGTIME_AGENT_*` env var pattern. |
| **Dependencies** | `pydantic-ai` only. Pydantic v2 already indirect dependency. |
| **Python 3.13** | Fully supported. |

Not recommended: LangGraph (heavy deps), CrewAI (multi-agent for single-agent problem), smolagents (code-exec security concern), OpenAI Agents SDK (vendor-locked).

### Browser automation: Playwright (direct Python API)

| Criterion | Assessment |
|---|---|
| **Integration** | `sync_playwright()` as Pydantic AI tool functions. Same process, zero overhead. |
| **Screenshots + cursor** | CSS/JS injection (~40 lines) renders synthetic cursor. `page.screenshot()` captures it. |
| **CloudFlare** | `playwright-stealth` / `camoufox` available. |

Not recommended: Stagehand/Browser Use (double LLM calls, no Langfuse), Selenium (superseded), Playwright MCP (needs Node.js, latency issues).

### Langfuse observability: Keep SDK, ensure coexistence with Pydantic AI

**Key finding:** Langfuse v4 is already OTel-native under the hood. The `@observe()` and `propagate_attributes()` decorators produce OTel spans internally. Pydantic AI's `Agent.instrument_all()` also produces OTel spans. Since both share the same `TracerProvider`, they coexist naturally — no migration needed.

**What stays the same:** Everything. `@observe_step()`, `@observe_provider()`, `langfuse.openai.OpenAI` wrapper, `set_observation_input/output()`, `langfuse_context.update_current_observation()`.

**What's added to `episodes/observability.py`:**
1. `setup()` function — calls `langfuse.get_client()` to eagerly initialize the OTel TracerProvider at startup (currently lazy). Also calls `Agent.instrument_all()` when Pydantic AI is installed.
2. Call `setup()` from `AppConfig.ready()` in `episodes/apps.py`

**For the agent strategy:**
- `Agent.instrument_all()` makes Pydantic AI tool calls and LLM calls appear in Langfuse automatically
- Agent recovery functions wrapped with `@observe_step("recovery_scraping")` → traces grouped by `session_id`
- Playwright screenshots attached via `_update_observation(metadata={"screenshot": base64_png})`
- No new dependencies for observability (Langfuse SDK already handles everything)

---

## 7. Key Files

| File | Change |
|---|---|
| `episodes/observability.py` | Add `setup()` for eager TracerProvider init + `Agent.instrument_all()` |
| `episodes/apps.py` | Call `observability.setup()` in `ready()` |
| `episodes/events.py` | **New.** `StepFailureEvent`, `classify_error()`, `build_failure_event()` |
| `episodes/recovery.py` | **New.** `RecoveryStrategy` ABC, two strategies, dispatcher |
| `episodes/models.py` | Add `PipelineEvent` + `RecoveryAttempt` models. Remove `NEEDS_REVIEW` status. |
| `episodes/processing.py` | Modify `complete_step()` and `fail_step()` to build events and send signals |
| `episodes/signals.py` | Add `step_failed` custom signal |
| `episodes/apps.py` | Connect `handle_step_failure` to `step_failed` signal |
| `episodes/admin.py` | `PipelineEventInline`, `PipelineEventAdmin`, `RecoveryAttemptInline`, "Needs Human Action" filter |
| `episodes/scraper.py` | Pass `exc=exc` to `fail_step()` (one-line change) |
| `episodes/downloader.py` | Pass `exc=exc` to `fail_step()` (one-line change) |
| `episodes/transcriber.py` | Pass `exc=exc` to `fail_step()` (one-line change) |
| `episodes/summarizer.py` | Pass `exc=exc` to `fail_step()` (one-line change) |
| `episodes/chunker.py` | Pass `exc=exc` to `fail_step()` (one-line change) |
| `episodes/extractor.py` | Pass `exc=exc` to `fail_step()` (one-line change) |
| `episodes/resolver.py` | Pass `exc=exc` to `fail_step()` (one-line change) |
| `ragtime/settings.py` | Recovery chain settings |
| `.env.sample` | `RAGTIME_RECOVERY_*` variables |
| `episodes/agents/` | **New package (Phase 4).** `scraper_agent.py` with Pydantic AI + Playwright |
| `pyproject.toml` | Add `pydantic-ai`, `playwright` |

---

## 8. Implementation Phases

### Phase 1: Event infrastructure
- `events.py` with `StepCompletedEvent`, `StepFailureEvent`, `classify_error()`
- `PipelineEvent` and `RecoveryAttempt` models (migration)
- Remove `NEEDS_REVIEW` from Episode.Status choices (migration)
- `step_completed` and `step_failed` custom signals
- Modify `complete_step()` to build success event and send `step_completed`
- Modify `fail_step()` to accept `exc`, build failure event, send `step_failed`
- Pass `exc=exc` in each pipeline step's except block (7 one-line changes)
- Signal handler to persist `PipelineEvent` records for both success and failure

### Phase 2: Recovery layer
- `recovery.py` with strategy ABC, dispatcher, and two strategies
- `HumanEscalationStrategy` creating `AWAITING_HUMAN` records
- Stub `AgentStrategy` (always escalates, behind feature flag)
- Wire signal handler in `apps.py`
- Add `observability.setup()` call in `apps.py:ready()` (eager TracerProvider init)
- Recovery settings in `settings.py` / `.env.sample`

### Phase 3: Admin integration
- `PipelineEventInline` on `EpisodeAdmin` (success + failure events)
- `PipelineEventAdmin` standalone view with filters (event_type, step_name, error_type)
- `RecoveryAttemptInline` on `EpisodeAdmin`
- "Needs Human Action" list filter
- Reprocess action resolves `AWAITING_HUMAN` records
- Remove NEEDS_REVIEW-related admin logic (editable fields, etc.)

### Phase 4: Agent strategy (behind feature flag)
- `episodes/agents/` package
- `scraper_agent.py`: Pydantic AI agent with Playwright browser tools
- `download_agent.py`: agent for download recovery
- `Agent.instrument_all()` in `setup()` for automatic Langfuse tracing
- Enable via `RAGTIME_RECOVERY_AGENT_ENABLED=True`

### Verification
- **Phase 1**: `uv run python manage.py test` — existing tests still pass. New tests for `classify_error()` and signal emission.
- **Phase 2**: Test human escalation → verify `RecoveryAttempt` created. Test stub agent → verify escalation to human. Test full chain → verify escalation order.
- **Phase 3**: Manual admin verification — inline visible, filter works, reprocess resolves attempts.
- **Phase 4**: Integration test with a known-failing episode URL → agent finds audio_url via Playwright → pipeline resumes. Langfuse trace shows screenshots.


If you need specific details from before exiting plan mode (like exact code snippets, error messages, or content you generated), read the full transcript at: /Users/rafa/.claude/projects/-Users-rafa-Develop-projects-ragtime/d7842f79-ffa8-4b5c-aa5c-336122a4a70d.jsonl

### Assistant

I'll start by reading the key existing files to understand the current codebase before implementing.

Now let me read the exact files I need to modify.

Now let me read the pipeline step files to see their fail_step patterns.

Now let me read the remaining files.

Now let me check the existing tests and the configure command.

Let me check the configure command quickly.

Good, I have a thorough understanding of the codebase. Let me create a branch and start implementing. This is a large feature spanning Phases 1-3 of the plan.

Now I'll implement all three phases. Let me start with Phase 1: Event infrastructure.

**Phase 1: Create `episodes/events.py`**

**Phase 1: Update models.py - Remove NEEDS_REVIEW, add PipelineEvent and RecoveryAttempt**

Now add the PipelineEvent and RecoveryAttempt models at the end of models.py:

**Phase 1: Update signals.py - add custom signals**

**Phase 1: Update processing.py - modify complete_step() and fail_step()**

**Phase 1: Pass `exc=exc` in each pipeline step's except block**

Also update the scraper to remove NEEDS_REVIEW — when incomplete, set FAILED instead:

Now update the remaining pipeline steps to pass `exc=exc`:

**Phase 2: Create `episodes/recovery.py`**

**Phase 2: Update apps.py — connect recovery handler, add observability setup**

**Phase 2: Add `setup()` to observability.py**

**Phase 2: Add recovery settings to settings.py**

**Phase 2: Update .env.sample**

**Phase 2: Update configure helpers**

**Phase 3: Update admin.py — add PipelineEvent and RecoveryAttempt admin**

Now let me generate the migration and run tests.

9 errors, all from `NEEDS_REVIEW` references in tests. Let me fix them.

Now fix the scraper tests:

Now fix the admin tests:

Now run tests again:

Three issues to fix:

1. Scraper: `error_message` not in `update_fields` for the incomplete metadata save
2. Configure wizard tests: the new Recovery system adds an extra prompt

Let me fix the scraper first:

Now let me check the configure test to understand the mock input pattern:

I need to add the Recovery `AGENT_ENABLED` prompt to both wizard tests. The Recovery system is non-shareable with a single field, so it goes through `_prompt_system` which calls `input()` for the `AGENT_ENABLED` field.

Now fix the second wizard test (`test_rerun_preserves_non_ragtime_lines`):

Now run tests again:

All 162 tests pass. Now let me write the new tests for the event infrastructure, recovery layer, and admin integration.

All 186 tests pass (162 existing + 24 new). Now let me create the documentation per CLAUDE.md requirements. I'll also check the planning session transcript location.

Now let me save the plan document and create the feature doc. Let me also check if the planning session transcript exists at the referenced path.

The plan was already saved from the planning session. Good. Now create the feature doc.

Now create the session transcripts. First the planning session:

While the planning session transcript is being generated, let me create the implementation session transcript and update the changelog.

Now update the CHANGELOG:

Let me check on the background agent and also update the README pipeline section to reflect the NEEDS_REVIEW removal.

Let me run the tests one final time to make sure everything is still good:

Let me also run the Django system checks:

Good. Now let me wait for the background agent to finish with the planning session transcript, then verify it was created properly.

The background agent hasn't finished yet. Let me check its progress:

The agent is still working on parsing the transcript. Let me create the planning session transcript directly since the planning session was primarily assistant-driven (single user request followed by extensive exploration and plan writing).

Now let me do a final review to make sure I haven't missed anything. Let me check for any remaining NEEDS_REVIEW references in non-doc files:

All remaining NEEDS_REVIEW references are in documentation files (historical docs, changelogs, plan docs). That's correct — we don't rewrite history.

Let me also run the check command one more time and make sure migrations are complete:

Everything looks good. Let me verify the complete list of changed files:

All files accounted for. Implementation is complete across all three phases. Here's a summary:

## Implementation Complete — Phases 1-3

### Phase 1: Event Infrastructure
- **`episodes/events.py`** (new) — `StepCompletedEvent`, `StepFailureEvent` dataclasses, `classify_error()` mapping 6 exception categories
- **`episodes/models.py`** — removed `NEEDS_REVIEW` status, added `PipelineEvent` and `RecoveryAttempt` models
- **`episodes/signals.py`** — added `step_completed` and `step_failed` custom signals
- **`episodes/processing.py`** — `complete_step()` and `fail_step()` now emit events and persist `PipelineEvent` records
- **7 pipeline steps** — each now passes `exc=exc` to `fail_step()`
- **`episodes/scraper.py`** — incomplete metadata sets `FAILED` instead of `NEEDS_REVIEW`

### Phase 2: Recovery Layer
- **`episodes/recovery.py`** (new) — `RecoveryStrategy` ABC, `AgentStrategy` (stub, behind feature flag), `HumanEscalationStrategy`, dispatcher with 5-attempt ceiling
- **`episodes/apps.py`** — connected recovery handler to `step_failed` signal, added `observability.setup()`
- **`episodes/observability.py`** — added `setup()` for eager TracerProvider init
- **`ragtime/settings.py`** — `RAGTIME_RECOVERY_CHAIN` and `RAGTIME_RECOVERY_AGENT_ENABLED`

### Phase 3: Admin Integration
- **`episodes/admin.py`** — `PipelineEventInline` (colour-coded), `RecoveryAttemptInline`, standalone `PipelineEventAdmin`/`RecoveryAttemptAdmin` with "Needs Human Action" filter, reprocess resolves `AWAITING_HUMAN` records

### Tests
- **186 tests pass** (162 existing + 24 new across `test_events.py` and `test_recovery.py`)

Ready for commit when you'd like.

### User

<task-notification>
<task-id>af867dea49546d657</task-id>
<tool-use-id>toolu_01DwKjaN4kqGVKDbTWht8jAV</tool-use-id>
<output-file>/private/tmp/claude-501/-Users-rafa-Develop-projects-ragtime/0c5715f3-fdef-4661-8a30-8185fee81bfe/tasks/af867dea49546d657.output</output-file>
<status>completed</status>
<summary>Agent "Create plan document" completed</summary>
<result>Plan document written to `/Users/rafa/Develop/projects/ragtime/doc/plans/decoupled-recovery-architecture.md`.</result>
<usage><total_tokens>12426</total_tokens><tool_uses>2</tool_uses><duration_ms>260553</duration_ms></usage>
</task-notification>
Full transcript available at: /private/tmp/claude-501/-Users-rafa-Develop-projects-ragtime/0c5715f3-fdef-4661-8a30-8185fee81bfe/tasks/af867dea49546d657.output

### Assistant

The background agent for the plan document completed (the planning session transcript was already created directly). Everything is in place — ready for your next instruction.

### User

<task-notification>
<task-id>a268f52ef6f4495fe</task-id>
<tool-use-id>toolu_01NcZRCT7udBqYrPfvRoQn9L</tool-use-id>
<output-file>/private/tmp/claude-501/-Users-rafa-Develop-projects-ragtime/0c5715f3-fdef-4661-8a30-8185fee81bfe/tasks/a268f52ef6f4495fe.output</output-file>
<status>completed</status>
<summary>Agent "Generate session transcripts" completed</summary>
<result>The planning session transcript has been written to `/Users/rafa/Develop/projects/ragtime/doc/sessions/2026-03-18-decoupled-recovery-architecture-planning-session.md`.

The session was primarily an agentic session where the user provided a single initial prompt asking about introducing agentic AI for pipeline failure recovery. The assistant then conducted extensive research using sub-agents, iterating through several design phases:

1. Framework evaluation (Pydantic AI selected over LangGraph, CrewAI, smolagents, OpenAI Agents SDK)
2. Browser automation analysis (Playwright direct Python API selected over Stagehand, Browser Use, Selenium, MCP)
3. Architecture evolution from "agent in pipeline" to a decoupled three-layer design (pipeline events, recovery layer, agent strategy)
4. Langfuse coexistence analysis (keep SDK, no OTel migration)
5. Simplifications (drop RetryStrategy, add success events, remove NEEDS_REVIEW status)

The transcript follows the format of the existing reference transcript at `doc/sessions/2026-03-17-clarify-extract-resolve-readme-planning-session.md`, with Session ID, Summary, and detailed `### User` / `### Assistant` conversation sections.</result>
<usage><total_tokens>48583</total_tokens><tool_uses>23</tool_uses><duration_ms>277620</duration_ms></usage>
</task-notification>
Full transcript available at: /private/tmp/claude-501/-Users-rafa-Develop-projects-ragtime/0c5715f3-fdef-4661-8a30-8185fee81bfe/tasks/a268f52ef6f4495fe.output

### Assistant

The planning session transcript has been updated with more detailed content. Both background agents have completed. Everything is ready — shall I commit and create a PR?

### User

Is it possible to make a commit for each phase or do you plan to make one commit for the whole feature?

### Assistant

Each phase builds on the previous one (Phase 2 imports from Phase 1's models/events, Phase 3 uses Phase 2's RecoveryAttempt), but the changes are separable into commits that each leave the codebase in a working state. Let me break it down:

**Commit 1 — Phase 1: Event infrastructure**
- `episodes/events.py`, model changes, signals, `processing.py` changes, `exc=exc` in all steps, scraper NEEDS_REVIEW removal, migration, `test_events.py`, updated existing tests

**Commit 2 — Phase 2: Recovery layer**  
- `episodes/recovery.py`, `apps.py` wiring, `observability.setup()`, settings, `.env.sample`, configure helpers, `test_recovery.py`, configure test fix

**Commit 3 — Phase 3: Admin integration**
- `admin.py` changes (inlines, filters, reprocess resolving AWAITING_HUMAN), admin test updates

**Commit 4 — Documentation**
- Plan, feature doc, session transcripts, changelog, README update

Want me to go ahead with this 4-commit approach?

### User

yes

### Assistant

4 clean commits on the feature branch:

1. **a7cf8b7** — Phase 1: Event infrastructure (15 files)
2. **9a8c620** — Phase 2: Recovery layer (8 files)
3. **a6c57ab** — Phase 3: Admin integration (2 files)
4. **d119ff2** — Documentation (6 files)

Working tree is clean. Ready to push and create a PR when you'd like.

### User

Create a PR

### Assistant

PR created: https://github.com/rafacm/ragtime/pull/69

5 review comments from **Copilot**. Here's the breakdown:

| # | File | Summary | Severity | Reviewer's suggestion | My recommendation |
|---|---|---|---|---|---|
| 1 | `scraper.py:143-147` | Incomplete metadata calls `fail_step()` without `exc`, so no `PipelineEvent` is persisted and `step_failed` signal never fires — recovery layer won't create a `RecoveryAttempt` | **High** — breaks the intended recovery flow for this specific case | Pass a synthetic exception or make `fail_step()` emit events without `exc` | **Fix**: pass `exc=ValueError("Incomplete metadata: missing required fields")` so the full event/recovery chain fires |
| 2 | `processing.py:73-75` | `ProcessingStep.objects.get()` in `complete_step()` is outside the `try` block — if step row is missing, it prevents run completion | **Medium** — defensive robustness | Move `.get()` inside the `try` block | **Fix**: move inside `try`, the existing `except Exception` will catch it |
| 3 | `processing.py:120-122` | Same issue in `fail_step()` — `.get()` outside `try` could mask the original error | **Medium** — defensive robustness | Move `.get()` inside the `try` block | **Fix**: move inside `try` |
| 4 | `admin.py:167-171` | With NEEDS_REVIEW removed, metadata fields are now read-only for all episodes, making human-fix-then-reprocess impossible from admin | **High** — breaks the human escalation workflow | Make metadata editable when episode is FAILED with AWAITING_HUMAN recovery | **Fix**: add condition to allow editing when FAILED + AWAITING_HUMAN |
| 5 | `migration 0018:14-18` | Migration removes `needs_review` from choices but doesn't migrate existing rows — episodes with `status='needs_review'` would be orphaned | **Medium** — data integrity on deploy | Add a data migration to convert `needs_review` → `failed` | **Fix**: add `RunPython` data migration step |

Comments 1 and 4 are genuinely important bugs. Comments 2-3 are good defensive improvements. Comment 5 is correct for production safety. Want me to fix all 5?

### User

go ahead

### Assistant

Now let me fix all 5 issues.

**Fix 1: scraper.py — pass synthetic exc for incomplete metadata**

**Fixes 2 & 3: processing.py — move `.get()` inside `try` blocks**

**Fix 4: admin.py — make metadata editable when FAILED + AWAITING_HUMAN**

**Fix 5: Add data migration for existing `needs_review` rows**

Now update the admin test for the new editable-when-awaiting-human behavior:

Run tests:

All 187 tests pass. Now commit and push:

Now reply to each review comment:

All 5 review comments addressed, fixed, and replied to:

1. **scraper.py** — synthetic `ValueError` now triggers full recovery chain
2. **processing.py complete_step()** — `.get()` moved inside `try`
3. **processing.py fail_step()** — `.get()` moved inside `try`
4. **admin.py** — metadata editable when FAILED + AWAITING_HUMAN
5. **migration 0018** — `RunPython` converts `needs_review` → `failed` before `AlterField`

3 new review comments from **Copilot**:

| # | File | Summary | Severity | Reviewer's suggestion | My recommendation |
|---|---|---|---|---|---|
| 1 | `scraper.py:172` | In the outer except block, `episode.error_message` is never set — episode stays FAILED with empty error message unlike other pipeline steps | **Low** — pre-existing pattern (was like this before this PR), but easy fix for consistency | Set `episode.error_message = str(exc)` and add `error_message` to `update_fields` | **Fix**: one-line consistency improvement |
| 2 | `recovery.py:15` | `PipelineEvent` imported but unused in this module | **Low** — dead import | Remove unused import | **Fix**: remove it |
| 3 | `apps.py:15` | `step_failed.connect()` without `dispatch_uid` can register duplicate handlers under Django autoreloader | **Medium** — could cause duplicate `RecoveryAttempt` rows | Add `dispatch_uid` to the connect call | **Fix**: add `dispatch_uid="recovery_step_failed"` |

All three are valid and straightforward. Want me to fix them?

### User

yes

### Assistant

All 3 comments fixed, pushed, and replied to in 99ec40b.

### User

Do we need to also review the intro text in "Processing Pipeline" in the README with these changes?

### Assistant

Yes — line 52 says "Any failure sets `status` to `failed` and halts the chain" which is incomplete now. It should mention the recovery layer. The step 2 description (line 68) was already updated.

The failures are unrelated to my README change. Let me investigate — the `dispatch_uid` fix should have prevented duplicates, and `RAGTIME_RECOVERY_AGENT_ENABLED` should be False by default.

The `.env` file has `RAGTIME_RECOVERY_AGENT_ENABLED=true`, which gets loaded via `dotenv` into settings. Tests that assume the default (`False`) need `override_settings`. The earlier test runs happened before this env var existed.

Now the `MultipleObjectsReturned` errors — when agent is enabled, both agent AND human strategies fire, creating 2 attempts. The tests expect only 1.

Now fix the integration test too:

All 187 tests pass. Now commit and push:

Good catch — the pipeline intro now reads:

> Any failure sets `status` to `failed`, emits a structured `step_failed` signal, and triggers the recovery layer which walks a configurable strategy chain (agent → human escalation).

Also fixed 3 recovery tests that were sensitive to the `.env` having `RAGTIME_RECOVERY_AGENT_ENABLED=true` — they now use `override_settings` to ensure isolation.

### User

Let's move the diagram for the processing pipeline to right after the section title

### Assistant

Done — the diagram now sits directly under `## Processing Pipeline`, with the explanatory paragraph following it.

No response requested.

### User

How do I remove a plugin?

### Assistant

The correct command is:

```
/plugin uninstall excalidraw@excalidraw-skill
```

Or from the CLI: `claude plugin uninstall excalidraw@excalidraw-skill`

Aliases `remove` and `rm` should also work. You can add `--scope project` or `--scope user` to target a specific scope, and `--keep-data` to preserve the plugin's persistent data directory.

### User

Generate an Excalidraw diagram for the Processing Pipeline

### Assistant

Generated the diagram at `doc/architecture/processing-pipeline.excalidraw` with 58 elements. It shows:

- **Title**: "RAGtime Processing Pipeline"
- **Pipeline U-shape** (10 steps): Submit → Scrape → Download → Transcribe → Summarize → Chunk → Extract → Resolve → Embed → Ready, with status labels below each step
- **Signal annotation**: "Each step dispatches the next via post_save signal → Django Q2 async task"
- **Recovery Layer** (dashed red box): step_failed signal → Recovery Dispatcher → Agent Strategy (stub) / Human Escalation, with "escalates" dashed arrow between strategies

You can open it in [excalidraw.com](https://excalidraw.com) or the VS Code Excalidraw extension to view and edit.

### User

I've added an SVG version. Can you replace the pipeline diagram in the README with this one?

### Assistant

Done — replaced the ASCII art with the SVG diagram reference.

### User

Commit and push the changes

### Assistant

Committed and pushed as `e4fd6c4`.

### User

Add a link to the Excalidraw diagram. When clicking on the diagram it should go to https://app.excalidraw.com/s/3Cob4pHK6Ge/3zFsvWxbOWQ

### Assistant

Done — clicking the diagram now opens the interactive Excalidraw version.

### User

Add the prefix "ragtime-" to both files and fix the references.

### Assistant

Done — files renamed to `ragtime-processing-pipeline.excalidraw` and `ragtime-processing-pipeline.svg`, README reference updated.

### User

I've merged the PR. What's left from this implementation plan?

### Assistant

Based on the plan in `doc/plans/decoupled-recovery-architecture.md`:

**Completed (this PR):**
- Phase 1: Event infrastructure
- Phase 2: Recovery layer
- Phase 3: Admin integration

**Remaining:**
- **Phase 4: Agent strategy** — the actual AI agent that can recover from scraping/download failures:
  - `episodes/agents/` package
  - Pydantic AI agent with Playwright browser tools (navigate pages, find audio URLs, bypass CloudFlare)
  - `Agent.instrument_all()` for Langfuse tracing
  - Replace the current stub `AgentStrategy` (which always escalates to human) with the real implementation

Phase 4 was explicitly scoped as a **future PR** in the plan.

### User

How do we move on then with Phase 4?

### Assistant

On `main` with latest changes pulled. Ready to plan Phase 4 — the Pydantic AI agent with Playwright browser tools for automated recovery of scraping/download failures. Want to start with a planning session?

### User

Shall I clear the context?

### Assistant

Yes, that would be good — this conversation has a lot of accumulated context from Phases 1-3. A fresh session will keep things focused for the Phase 4 planning.

### User

Can you provide a summary for planning Phase 4 so I can start the planning session with that?

### Assistant

Here's the context to kick off the Phase 4 planning session:

---

**Phase 4: Agent Recovery Strategy for Pipeline Failures**

**Context:** Phases 1-3 (merged in PR #69) introduced a decoupled recovery architecture:
- Pipeline steps emit structured `step_failed` signals with error classification
- A recovery layer walks a strategy chain: Agent → Human Escalation
- `AgentStrategy` in `episodes/recovery.py` is currently a **stub** — it always returns `should_escalate=True` and is gated behind `RAGTIME_RECOVERY_AGENT_ENABLED=False`
- `PipelineEvent` and `RecoveryAttempt` models track all attempts with admin visibility

**Goal:** Replace the stub `AgentStrategy` with a real Pydantic AI agent that can autonomously recover from scraping (step 2) and download (step 3) failures by finding audio URLs using browser automation.

**Technology decisions (from planning session d7842f79):**
- **Pydantic AI** — model-agnostic, type-safe, `agent.run_sync()` works in Django Q2 tasks
- **Playwright** (direct Python API) — browser tools as Pydantic AI tool functions, headless-only
- **Langfuse integration** — `Agent.instrument_all()` shares existing `TracerProvider`, screenshots attached as `LangfuseMedia`

**Key files:**
- Plan: `doc/plans/decoupled-recovery-architecture.md` (Phase 4 section)
- Recovery layer: `episodes/recovery.py` (stub `AgentStrategy` to replace)
- Events: `episodes/events.py` (`StepFailureEvent` with `cached_data` containing scraped HTML, error context)
- Observability: `episodes/observability.py` (existing Langfuse setup)
- Settings: `RAGTIME_RECOVERY_AGENT_ENABLED`, `RAGTIME_RECOVERY_CHAIN`

**Scope from the plan:**
- `episodes/agents/` package
- Pydantic AI agent with Playwright browser tools
- `Agent.instrument_all()` for Langfuse tracing
- Screenshots with cursor overlay for observability

---

### User

Great! Thanks! Bye!

### Assistant

Bye! Good luck with Phase 4 planning!
