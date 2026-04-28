# Download Agent, Podcast Indexes, and DBOS State-of-Truth

**Date:** 2026-04-28

## Problem

The pipeline carried two layers of state. DBOS already records every workflow run, every step invocation, every input/output/exception. On top of that, four Django models (`ProcessingRun`, `ProcessingStep`, `PipelineEvent`, `RecoveryAttempt`) duplicated most of that information at the wrong granularity — DBOS saw `execute_pipeline_step` called eight times with different string args; humans saw `DOWNLOADING`, `TRANSCRIBING`, … . A separate "recovery layer" (`step_failed` signal → `AgentStrategy` → `HumanEscalationStrategy`) ran a Pydantic AI Playwright agent against fetch-details and download failures, with `RecoveryAttempt` rows tracking attempts and an `awaiting_human` workflow.

The recovery agent's stated job was "find the audio URL and download it" — i.e. it was conceptually a download step that ran after the download step failed. And ARD-style publishers (audio URL hidden behind a 3-dots menu) needed a third deterministic option below the agent: podcast indexes (fyyd, podcastindex.org) carry the publisher's RSS-feed enclosure URL even when the publisher's HTML doesn't.

## Changes

* **Episode.guid** field added (CharField, blank). The fetch_details Pydantic AI agent extracts it from `urn:` URIs / `itunes:episodeGuid` / `<guid>` tags / `data-guid` attributes; used as a hint by the download agent's `lookup_podcast_index` tool.
* **fetch_details `REQUIRED_FIELDS`** relaxed from `("title", "audio_url")` to `("title",)`. The download step now owns audio-URL discovery, so fetch-details is allowed to advance with title-only.
* **`episodes/podcast_indexes/`** new package:
  * `base.py` — `PodcastIndex` ABC + `EpisodeCandidate` dataclass.
  * `fyyd.py` — open API, term search.
  * `podcastindex.py` — GUID lookup → term-search fallback, sha1-signed `X-Auth-Key` / `X-Auth-Date` / `Authorization` headers.
  * `factory.py` — fans out `RAGTIME_PODCAST_INDEXES` (ordered list), merges + dedupes by `audio_url`.
* **`episodes/agents/download{,_browser,_deps,_tools}.py`** — renamed from `recovery*`. New tool: `lookup_podcast_index` calls into `episodes/podcast_indexes`. `DownloadDeps` carries `title`, `show_name`, `guid`, drops recovery-specific `error_type`/`http_status` fields.
* **`episodes/downloader.py`** rewrite — three-tier cascade:
  1. `wget` on `episode.audio_url` (cheap path).
  2. Pydantic AI download agent (`run_download_agent`).
  3. Raise `DownloadFailed(episode_id, sources_tried, wget_error, agent_message)`.
  Returns a typed `DownloadResult` on success.
* **Recovery layer deleted** — `episodes/recovery.py`, `episodes/agents/recovery_resume.py`, `step_failed` Django signal, `RAGTIME_RECOVERY_*` settings (with env-var fallback during the transition for `RAGTIME_DOWNLOAD_AGENT_*`), `RecoveryAttemptAdmin.retry_agent_recovery` action, `run_agent_recovery` DBOS workflow.
* **Models dropped** — `ProcessingRun`, `ProcessingStep`, `PipelineEvent`, `RecoveryAttempt`. Migration `0023_drop_processing_pipeline_models`. DBOS owns workflow state; `Episode.status` + `Episode.error_message` carry the user-facing summary.
* **Workflow restructured** — `process_episode` is now one explicit `@DBOS.step()` per pipeline phase (`fetch_details_step_`, `download_step`, `transcribe_step`, `summarize_step`, `chunk_step`, `extract_step`, `resolve_step`, `embed_step`) plus a `_bootstrap_status` step. No more dynamic-dispatch importlib lookup; no more bookkeeping steps. Successful steps return a typed `StepOutput`; failures propagate up and DBOS records the exception. `workflow_id_for(episode_id, attempt)` returns the deterministic `episode-<id>-run-<n>` ID that replaces the dropped `unique_running_run_per_episode` partial index.
* **Admin** — replaced `ProcessingRunAdmin` / `PipelineEventAdmin` / `RecoveryAttemptAdmin` with a single Episode-detail "View workflow steps" link backed by `DBOS.list_workflow_steps`. Falls back to an empty list when DBOS is offline so admin keeps loading.
* **`processing.py`** reduced to no-op shims — step modules don't have to be rewritten in this PR. Future cleanup will inline & delete.
* **Documentation** — `README.md` pipeline summary, `doc/README.md` updated step-3 description, "Recovery" section replaced with a "Download cascade" section, recovery Excalidraw flagged stale.
* **Configuration** — `.env.sample` and the `manage.py configure` wizard learn the new env vars (`RAGTIME_DOWNLOAD_AGENT_*`, `RAGTIME_PODCAST_INDEXES`, `RAGTIME_FYYD_API_KEY`, `RAGTIME_PODCASTINDEX_API_KEY`/`_SECRET`).

## Key parameters

| Variable | Default | Notes |
|----------|---------|-------|
| `RAGTIME_DOWNLOAD_AGENT_API_KEY` | empty | Falls back to the deprecated `RAGTIME_RECOVERY_AGENT_API_KEY` for one release. |
| `RAGTIME_DOWNLOAD_AGENT_MODEL` | `openai:gpt-4.1-mini` | Any Pydantic AI model string. |
| `RAGTIME_DOWNLOAD_AGENT_TIMEOUT` | `120` | Seconds; ceiling on a single agent run. |
| `RAGTIME_PODCAST_INDEXES` | empty | Comma-separated ordered list. Empty = no index lookup; agent goes straight to browsing. |
| `RAGTIME_FYYD_API_KEY` | empty | Optional; only raises rate limits. |
| `RAGTIME_PODCASTINDEX_API_KEY` / `_SECRET` | empty | Required when `podcastindex` is in the list. |

## Verification

```bash
docker compose down -v && docker compose up -d
uv run python manage.py migrate

# Cheap path — most episodes
uv run python manage.py submit_episode "<RSS-derived URL with audio in HTML>"
# Expect: status: ready. dbos workflow steps … shows download_step output
# StepOutput(step_name="downloading"), no agent invoked.

# Index path — ARD example
uv run python manage.py submit_episode "https://www.ardsounds.de/episode/urn:ard:episode:fdcf93eef8395b35/"
# Expect: status: ready, audio file present. dbos workflow steps shows
# download_step succeeded; admin "View workflow steps" link surfaces the
# same trace in the browser.

# Agent fallback path — JS-only player not indexed
uv run python manage.py submit_episode "<JS-only player URL not indexed>"
# Expect: status: ready (when agent succeeds) or status: failed with
# DownloadFailed(...) recorded in DBOS.

# Verify the workflow trace mirrors PIPELINE_STEPS
uv run dbos workflow steps "episode-1-run-1"
# Expect 9 entries: _bootstrap_status, fetch_details_step_, download_step,
# transcribe_step, summarize_step, chunk_step, extract_step, resolve_step,
# embed_step. No bookkeeping noise.
```

## Files modified

| File | Change |
|------|--------|
| `episodes/models.py` | Added `Episode.guid`. Dropped `ProcessingRun`, `ProcessingStep`, `PipelineEvent`, `RecoveryAttempt`. |
| `episodes/migrations/0022_add_episode_guid.py` | New migration adding `guid` field. |
| `episodes/migrations/0023_drop_processing_pipeline_models.py` | New migration dropping the four pipeline models. |
| `episodes/agents/fetch_details.py` | System prompt + `EpisodeDetails` schema gain `guid`. |
| `episodes/fetch_details_step.py` | `REQUIRED_FIELDS = ("title",)`. `guid` flows into the merge + save. |
| `episodes/podcast_indexes/__init__.py` + `base.py` + `fyyd.py` + `podcastindex.py` + `factory.py` | New package — provider abstraction, two implementations, fan-out factory. |
| `episodes/agents/download.py` | Renamed from `recovery.py`. New `lookup_podcast_index` tool. `DownloadDeps` shape. `run_download_agent(episode_id, …)` entry point. |
| `episodes/agents/download_browser.py` | Renamed from `recovery_browser.py`. |
| `episodes/agents/download_deps.py` | Renamed from `recovery_deps.py`. `DownloadDeps` + `DownloadAgentResult.source` field. |
| `episodes/agents/download_tools.py` | Renamed from `recovery_tools.py`. New `lookup_podcast_index` tool fanning out to `episodes.podcast_indexes`. |
| `episodes/agents/recovery_resume.py` | Deleted. |
| `episodes/recovery.py` | Deleted. |
| `episodes/downloader.py` | Three-tier cascade. `DownloadResult` / `DownloadFailed`. |
| `episodes/workflows.py` | One `@DBOS.step()` per pipeline phase. Bookkeeping steps removed. `workflow_id_for()` helper. |
| `episodes/processing.py` | Reduced to no-op shims. |
| `episodes/signals.py` | Drop `step_completed` / `step_failed` Signal objects. |
| `episodes/events.py` | Slimmed to dataclasses + `classify_error`. |
| `episodes/apps.py` | Drop the recovery `step_failed` connect call. |
| `episodes/admin.py` | Drop ProcessingRun/PipelineEvent/RecoveryAttempt admin classes. New `dbos_steps_view` + URL + template, `dbos_steps_link` field on Episode change form. |
| `episodes/templates/admin/episodes/episode/dbos_steps.html` | New template for the per-step DBOS audit page. |
| `episodes/telemetry.py` | Switch session ID from `processing-run-<id>-…` to per-episode. |
| `ragtime/settings.py` | Drop `RAGTIME_RECOVERY_*`. Add `RAGTIME_DOWNLOAD_AGENT_*`, `RAGTIME_PODCAST_INDEXES`, `RAGTIME_FYYD_API_KEY`, `RAGTIME_PODCASTINDEX_API_KEY` / `_SECRET`. |
| `core/management/commands/_configure_helpers.py` | Replace "Recovery" wizard section with "Download Agent" + "Podcast Indexes". |
| `.env.sample` | Reflect the env-var changes. |
| `episodes/tests/test_recovery.py`, `episodes/tests/test_agent_resume.py` | Deleted. |
| `episodes/tests/test_events.py` | Slimmed to `classify_error` tests. |
| `episodes/tests/test_admin.py` | Drop recovery admin tests. Add DBOS-steps view tests. |
| `episodes/tests/test_fetch_details_step.py` | Drop recovery-aware regression test. New tests for `guid` extraction + title-only success path. |
| `episodes/tests/test_agent_tools.py` | `RecoveryDeps` → `DownloadDeps`. |
| `episodes/tests/test_podcast_indexes.py` | New — 11 tests covering provider behaviour + factory. |
| `core/tests/test_configure.py` | Updated wizard input lists for the new sections. |
| `README.md`, `doc/README.md`, `CHANGELOG.md` | Documentation updates. |
