# Download Agent, Podcast Indexes, and DBOS State-of-Truth

**Date:** 2026-04-28

## Goal

Consolidate the pipeline's failure-recovery story into the `Download` step itself by turning it into a Pydantic AI agent (mirroring `Fetch Details` from PR #107), and eliminate the parallel Django state machine (`ProcessingRun` / `ProcessingStep` / `PipelineEvent` / `RecoveryAttempt`) that duplicates DBOS's own workflow records. Add **podcast indexes** (fyyd, podcastindex.org) as a deterministic fallback the agent can call when the publisher's HTML hides the audio URL behind interactive UI (the canonical case is ARD Sounds, where `Herunterladen` lives behind a 3-dots menu).

The result: one agent per LLM-driven step, one source of truth for workflow state (DBOS), and a 3-tier cascade in `Download` (`wget` → podcast index → Playwright agent) that handles publishers ranging from clean RSS-fed sites to JS-only player pages.

## Scope

- **In scope:**
  - Add `Episode.guid` field + migration; extend the `fetch_details` agent to extract it; relax `REQUIRED_FIELDS` in `fetch_details_step.py` to `("title",)` only (audio_url no longer mandatory at end of fetch-details).
  - New `episodes/podcast_indexes/` provider abstraction with `base.py` (ABC), `fyyd.py`, `podcastindex.py`, `factory.py`. Configurable via `RAGTIME_PODCAST_INDEXES` ordered list + per-provider API keys.
  - Convert `episodes/downloader.py` to invoke a Pydantic AI agent. Reuse the existing recovery agent's Playwright tools by renaming the cluster (`agents/recovery*` → `agents/download*`). Add `lookup_podcast_index` as a new tool. Cheap path first: if `episode.audio_url` is set, `wget` it directly; only fall back to the agent when wget fails or the URL is missing.
  - Delete the recovery layer entirely: `episodes/recovery.py`, `RecoveryAttempt` model, `run_agent_recovery` workflow, `step_failed` signal, recovery-specific fields on `StepFailureEvent` (`error_type`, `http_status`, `exception_class`, `attempt_number`, `cached_data`), `classify_error()`, `RAGTIME_RECOVERY_*` settings, related admin views, related tests.
  - Drop `ProcessingRun`, `ProcessingStep`, `PipelineEvent` models + migration. DBOS owns workflow state. `Episode.status` + `Episode.error_message` carry user-facing summary.
  - Restructure `episodes/workflows.py`: one explicit `@DBOS.step()` per pipeline phase (`fetch_details_step`, `download_step`, `transcribe_step`, …), drop the bookkeeping steps (`create_run_step`, `is_run_still_active`, `did_step_complete`, `mark_run_failed`, `get_pending_resume_step`). `dbos workflow steps <id>` then mirrors `PIPELINE_STEPS` exactly.
  - Convert per-step success/failure detail to **structured return values** (success path, e.g. `DownloadResult` dataclass) and **custom exceptions** (failure path, e.g. `DownloadFailed` carrying `error_type`, `http_status`, `sources_tried`). DBOS records both verbatim — replaces what `PipelineEvent.context` and the structured fields used to carry.
  - Replace `ProcessingRunAdmin` / `PipelineEventAdmin` / `RecoveryAttemptAdmin` with a single Episode-detail admin view that reads `DBOS.list_workflow_steps(workflow_id)` and renders the per-step output/error.
  - Set deterministic workflow IDs on enqueue (`f"episode-{episode_id}-run-{n}"`) so DBOS dedup replaces the `unique_running_run_per_episode` DB constraint.
  - Update `.env.sample`, `core/management/commands/configure.py`, `CHANGELOG.md`, `README.md` (pipeline summary table), `doc/README.md` (step descriptions), Excalidraw flag.

- **Out of scope (deferred):**
  - Index-based cheap path inside `fetch_details` (i.e. querying indexes *before* the LLM to avoid LLM cost on indexed episodes). Land download-with-indexes first, measure miss rate and LLM cost, then decide.
  - Self-hosting DBOS Conductor for an ops UI. The new admin view is enough for now.
  - Migrating other pipeline steps (`Transcribe`, `Summarize`, etc.) to the agent pattern — their failure modes don't currently need agent recovery.
  - Pre-prod data: not preserved through these migrations. Per project memory (`feedback_reembed_ok_preprod.md`), full Postgres regen + re-ingest is acceptable. The `RecoveryAttempt`, `ProcessingRun`, `ProcessingStep`, `PipelineEvent` rows are simply dropped along with their tables.

## Decisions

### Recovery layer fate

- **Delete entirely.** With download-as-agent owning its own retry-with-tools logic, the strategy chain (`AgentStrategy`, `HumanEscalationStrategy`) and the `step_failed` Django signal have no remaining consumer.
- **Why deletion over incremental shrinkage:** the recovery agent's stated job is "find the audio URL and download it" — i.e. it is conceptually a download step that runs after the download step fails. Inlining it into download is the natural collapse, not a refactor.

### Fetch-details fallback

- **Relax `REQUIRED_FIELDS` to `("title",)` only.** Drop `audio_url` from the contract. The download agent now owns audio-URL discovery for cases where fetch-details returns title-only.
- **Why not** keep audio_url required: would force every `audio_url`-extraction failure to remain in `FETCHING_DETAILS`, requiring the same recovery hop we're deleting.
- **Add `Episode.guid`** (CharField, blank, default ""). Extracted by the fetch-details agent. Used as a hint to the podcast-index lookup, though title + show + date is the more reliable cross-platform key (ARD's `urn:ard:episode:*` URN is not what fyyd/podcastindex use; verified against fyyd's API — fyyd indexes the same WDR episode under the WDR media filename).

### Podcast indexes — placement

- **Agent-visible tool, not pre-agent step.** The download agent has `lookup_podcast_index(title, show_name, guid)` alongside `find_audio_links`, `intercept_audio_requests`, `click_element`, etc. Single agent run; agent decides what to try.
- **Why not** a deterministic pre-agent tier: agent-visible tooling is more flexible; the cost difference is small once the cheap path (wget on known URL) is in front of the agent for the happy case.
- **Why not** a separate pipeline step: would add status enum entries, admin views, and migration for what is one conditional fetch.

### Download cascade — cheap path first

- **`wget` first, agent second.** Mirrors the `_has_required_fields` short-circuit in `fetch_details_step.py:95-99`. If `episode.audio_url` is present and `wget` returns 200, save and complete. Otherwise, invoke the agent.
- **Why:** most episodes have a working URL from fetch-details; running the agent on every download is multi-cents per episode for a deterministic decision.

### Tool shape

- **One generic `lookup_podcast_index(title: str, show_name: str = "", guid: str = "") -> list[EpisodeCandidate]` tool**, fanning out internally to all configured indexes in `RAGTIME_PODCAST_INDEXES` order. Returns merged candidates with `(audio_url, title, show_name, duration_seconds, source_index)`.
- **Why not** one-tool-per-index: the agent has no useful priors on which index covers a given show; fan-out is faster than sequential agent decisions across N tools.
- **Identifier strategy:** title + show + published_at as primary key; GUID as a hint when present. fyyd does not support GUID search; podcastindex does but the GUID space is not portable across publishers.

### Model deletions

- **Drop `ProcessingRun`, `ProcessingStep`, `PipelineEvent` (in addition to `RecoveryAttempt`).** Pure DBOS state-of-truth.
- **Why not** keep a slim `PipelineEvent`: with the recovery layer gone, no consumer outside admin display reads it; admin can read DBOS records directly via `DBOS.list_workflow_steps(...)`.
- **Why not** keep `ProcessingRun` for the unique constraint: replaceable by deterministic DBOS workflow IDs (`f"episode-{episode_id}-run-{n}"`); DBOS refuses duplicate IDs.

### Per-step observability via DBOS

- **Structured return values for success.** Each pipeline step returns a typed dataclass (e.g. `DownloadResult(success=True, source="fyyd", audio_url=..., bytes_downloaded=...)`). Visible via `dbos workflow steps <workflow_id>`.
- **Custom exceptions for failure.** `DownloadFailed(error_type, http_status, sources_tried, message)`, `FetchDetailsFailed(...)`, etc. The exception class + args are what DBOS records.
- **Why this works:** DBOS has no `add_step_attribute` API; the only persisted-with-the-step values are the input, the output, and the exception. Encoding domain detail into output/exception types is the canonical idiom.

### Workflow shape

- **One `@DBOS.step()` per pipeline phase.** `fetch_details_step`, `download_step`, `transcribe_step`, `summarize_step`, `chunk_step`, `extract_step`, `resolve_step`, `embed_step`. Each wraps the existing module-level function but is the unit of DBOS checkpointing.
- **Drop the bookkeeping steps** (`create_run_step`, `is_run_still_active`, `did_step_complete`, `mark_run_failed`, `get_pending_resume_step`, `mark_queued`). They exist only to maintain `ProcessingRun`/`ProcessingStep`, which are being deleted.
- **Manual retry** = enqueue a new `process_episode` workflow with the desired `from_step`. Same mechanism the deleted `run_agent_recovery` used for resume; admin action wires to `episode_queue.enqueue(process_episode, episode_id, from_step=...)`.

### Module layout

```
episodes/
├── downloader.py                      ← orchestration only (cheap path + agent invoke)
├── agents/
│   ├── _model.py                      ← unchanged
│   ├── fetch_details.py               ← unchanged (extends to extract guid)
│   ├── download.py                    ← was agents/recovery.py
│   ├── download_browser.py            ← was agents/recovery_browser.py
│   ├── download_deps.py               ← was agents/recovery_deps.py
│   ├── download_tools.py              ← was agents/recovery_tools.py + new lookup_podcast_index
│   └── (download_resume.py removed; resume is implicit in cheap-path → agent flow)
└── podcast_indexes/                   ← NEW
    ├── __init__.py
    ├── base.py                        ← PodcastIndex ABC, EpisodeCandidate dataclass
    ├── factory.py                     ← build chain from RAGTIME_PODCAST_INDEXES
    ├── fyyd.py                        ← fyyd.de client (no API key required)
    └── podcastindex.py                ← podcastindex.org client (auth-key + auth-date headers)
```

`recovery.py`, `events.py` (slimmed or deleted), `models.py` (model removals), `workflows.py` (rewrite), `admin.py` (model-admin removals + DBOS-backed step view), `apps.py` (signal disconnect), `tests/test_recovery.py` (deleted), `tests/test_events.py` (slimmed), `tests/test_admin.py` (updated).

### Configuration

New env vars:

- `RAGTIME_PODCAST_INDEXES` — comma-separated ordered list, e.g. `"podcastindex,fyyd"`. Empty = no index lookup; agent must rely on browser tools.
- `RAGTIME_PODCASTINDEX_API_KEY`, `RAGTIME_PODCASTINDEX_API_SECRET` — required if `podcastindex` is in the list.
- `RAGTIME_FYYD_API_KEY` — optional (fyyd's read API is open, key only raises rate limits).

Removed env vars:

- `RAGTIME_RECOVERY_AGENT_ENABLED`, `RAGTIME_RECOVERY_AGENT_MODEL`, `RAGTIME_RECOVERY_AGENT_API_KEY`, `RAGTIME_RECOVERY_AGENT_TIMEOUT`, `RAGTIME_RECOVERY_CHAIN`. Their behavior is absorbed into `RAGTIME_DOWNLOAD_AGENT_*` (rename) and the implicit always-on cheap-path-first flow.

Renamed env vars (recovery → download):

- `RAGTIME_RECOVERY_AGENT_MODEL` → `RAGTIME_DOWNLOAD_AGENT_MODEL`
- `RAGTIME_RECOVERY_AGENT_API_KEY` → `RAGTIME_DOWNLOAD_AGENT_API_KEY`
- `RAGTIME_RECOVERY_AGENT_TIMEOUT` → `RAGTIME_DOWNLOAD_AGENT_TIMEOUT`

Update `.env.sample` and `core/management/commands/configure.py` accordingly.

### Documentation & changelog

- `README.md`: refresh the pipeline summary table (no change to the 10-step list, but the per-step description for `download` mentions the agent + indexes; the recovery-layer paragraph in the architecture section is removed).
- `doc/README.md`: update the `download` step description; remove the standalone "Recovery layer" section.
- `CHANGELOG.md`: entry under `## 2026-04-28` with `### Added`, `### Changed`, `### Removed`, marked `**BREAKING**` for env-var renames and the dropped models.
- Excalidraw diagrams: flag as out-of-date in the implementation feature doc; do not regenerate in this PR.

### Commit shape (single PR, several commits)

Per the user's solo-developer preference, this is one PR (`feature/download-agent-and-recovery-removal`) with the following commits, each independently reviewable:

1. `Plan + planning session transcript` (this commit).
2. `Add Episode.guid field, migration, fetch_details agent extraction, relax REQUIRED_FIELDS`.
3. `Add podcast_indexes provider abstraction (fyyd, podcastindex) with tests`.
4. `Convert download step to Pydantic AI agent; reuse browser tools, add lookup_podcast_index tool`.
5. `Delete recovery layer (recovery.py, RecoveryAttempt model, run_agent_recovery workflow, step_failed signal, related settings/admin/tests)`.
6. `Drop ProcessingRun, ProcessingStep, PipelineEvent; restructure DBOS workflow with one step per pipeline phase; structured return values + custom exceptions`.
7. `Replace removed admin views with DBOS.list_workflow_steps-backed Episode admin view`.
8. `Update .env.sample, configure wizard, README, doc/README, CHANGELOG; feature doc + implementation session transcript`.

Each commit runs `uv run python manage.py test` green before the next is started, per the test-before-commit feedback memory.

## Verification

After all commits land, verify on-device:

```bash
# Clean slate (pre-prod data freedom — full regen is acceptable)
docker compose down -v && docker compose up -d
uv run python manage.py migrate

# Submit a known-clean episode (cheap path)
uv run python manage.py submit_episode "<RSS-derived URL with audio in HTML>"
# Expect: download_step returns DownloadResult(source="wget", ...) — no agent invoked

# Submit an ARD episode (forces index lookup)
uv run python manage.py submit_episode "https://www.ardsounds.de/episode/urn:ard:episode:fdcf93eef8395b35/"
# Expect: download_step returns DownloadResult(source="fyyd", audio_url="https://wdrmedien-a.akamaihd.net/...")

# Submit an episode neither in HTML nor in indexes (forces Playwright)
uv run python manage.py submit_episode "<JS-only player URL not indexed>"
# Expect: download_step returns DownloadResult(source="agent", ...) or raises DownloadFailed

# Verify DBOS workflow trace mirrors PIPELINE_STEPS
uv run dbos workflow list --status SUCCESS | head -1   # grab a workflow id
uv run dbos workflow steps <workflow_id>
# Expect 8 steps: fetch_details_step, download_step, transcribe_step, ..., embed_step
# No bookkeeping steps (create_run_step etc.) in the output.

# Verify admin Episode detail page shows DBOS-derived per-step status
# Visit /admin/episodes/episode/<id>/ — confirm steps render with success/error detail
# pulled from DBOS.list_workflow_steps, not from ProcessingRun/Step/PipelineEvent.
```

## Open follow-ups

- **Index hit-rate measurement.** After this PR, log `DownloadResult.source` per episode for a week. If the `agent` fraction is small enough, deferring the fetch-details cheap-path-via-index is the right call. If `fyyd`/`podcastindex` consistently cover the same episodes the LLM extracts in fetch-details, that's the trigger to extend.
- **Workflow ID collision policy.** Decide whether re-running the same `(episode_id, run_n)` should be a no-op (DBOS rejects duplicate ID) or whether the admin "retry" action should compute the next free `run_n`. Probably the latter.
- **Conductor / self-hosted dashboard.** The new admin view covers per-episode visibility but not cross-episode queue health. Revisit Conductor self-hosting if/when the queue depth becomes operationally interesting.
