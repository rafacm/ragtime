# Download Agent and Recovery Removal — Implementation Session

**Date:** 2026-04-28

**Session ID:** ebabe827-3272-4fab-b02e-805978a81ae5

## Summary

Implementation of the plan in `doc/plans/2026-04-28-download-agent-and-recovery-removal.md`. Delivered as one PR / branch (`feature/download-agent-and-recovery-removal`) with seven independently-reviewable commits:

1. Plan + planning session transcript (already on branch).
2. `Episode.guid` field + migration; fetch_details agent extracts it; `REQUIRED_FIELDS = ("title",)`.
3. New `episodes/podcast_indexes/` package — `PodcastIndex` ABC, `EpisodeCandidate` dataclass, fyyd + podcastindex clients, fan-out factory + dedup. 11 new tests.
4. Download step converted to Pydantic AI agent + recovery layer removed (collapsed plan commits 4 + 5; the rename `agents/recovery*` → `agents/download*` IS the recovery removal — splitting them across two commits would require throwaway compatibility shims). Includes `lookup_podcast_index` tool, `DownloadDeps`/`DownloadAgentResult.source`, three-tier `wget → agent → DownloadFailed` cascade in `downloader.py`.
5. Drop `ProcessingRun` / `ProcessingStep` / `PipelineEvent` / `RecoveryAttempt`. Restructure DBOS workflow: one `@DBOS.step()` per pipeline phase, no bookkeeping steps, structured `StepOutput` return values, custom exceptions for failure. `processing.py` → no-op shims.
6. DBOS-backed Episode admin view — custom URL `<id>/dbos-steps/`, template renders per-step `function_name` + output + error from `DBOS.list_workflow_steps`. Falls back to empty list when DBOS isn't running.
7. `.env.sample`, configure wizard, README + doc/README + CHANGELOG entries, feature doc + this implementation transcript.

Final test suite: 336 tests passing.

## Detailed conversation

### User

> Implement the plan described in the first commit in this PR

### Assistant

Read the first commit (`8d33162`) and pulled out the plan from `doc/plans/2026-04-28-download-agent-and-recovery-removal.md`. Surveyed the current state of the code before touching anything: `episodes/models.py` (the four soon-to-be-deleted models), `episodes/workflows.py` (the dynamic-dispatch workflow + bookkeeping steps), `episodes/downloader.py`, `episodes/fetch_details_step.py`, `episodes/recovery.py`, `episodes/agents/recovery.py` + `recovery_browser.py` + `recovery_deps.py` + `recovery_tools.py` + `recovery_resume.py`, `episodes/events.py`, `episodes/processing.py`, `episodes/admin.py`, `episodes/signals.py`, `episodes/apps.py`, `ragtime/settings.py`, `core/management/commands/_configure_helpers.py`, `.env.sample`, `CHANGELOG.md`, and the test files that referenced any of these (`test_recovery.py`, `test_agent_resume.py`, `test_agent_tools.py`, `test_admin.py`, `test_fetch_details_step.py`, `test_events.py`, `test_signals.py`, `core/tests/test_configure.py`).

Set up an eight-task tracker mirroring the plan's commit list and proceeded commit-by-commit with `uv run python manage.py test` green at each boundary, per the test-before-commit feedback memory.

**Commit 2 — Episode.guid + fetch_details + relax REQUIRED_FIELDS.** Added `Episode.guid` (CharField, blank, max_length=500). Generated migration `0022_add_episode_guid`. Extended the fetch_details Pydantic AI agent: added `guid: str | None = None` to `EpisodeDetails` and a system-prompt rule explaining where to look (`urn:` URIs, `itunes:episodeGuid`, `<guid>` tags, `data-guid`/`data-episode-id` attrs). Relaxed `REQUIRED_FIELDS` from `("title", "audio_url")` to `("title",)` — the download step now owns audio-URL discovery. Added `guid` to the empty-field-only merge and the `update_fields` save list. Updated tests: removed the now-stale `test_incomplete_extraction_fails` (audio_url is no longer required), added `test_title_only_advances_to_downloading`, `test_missing_title_fails`, `test_extracts_guid`. Adjusted the recovery-status regression test to omit `title` instead of `audio_url` to keep its failure-path assertions valid.

**Commit 3 — `episodes/podcast_indexes/`.** Created the package with five files: `__init__.py` re-exports `EpisodeCandidate`, `PodcastIndex`, `lookup_episode_candidates`. `base.py` defines the ABC + frozen dataclass (`audio_url` plus optional `title`/`show_name`/`duration_seconds`/`source_index`). `fyyd.py` calls `https://api.fyyd.de/0.2/search/episode?term=…&count=10`, builds candidates from the `data` array's `enclosure` URLs, swallows `httpx.HTTPError`/`ValueError` and returns `[]`. `podcastindex.py` builds the sha1-signed `X-Auth-Key` / `X-Auth-Date` / `Authorization` header trio, tries `/episodes/byguid?guid=…` first when a GUID is provided, falls back to `/search/byterm?q=…`. `factory.py` reads `RAGTIME_PODCAST_INDEXES` (comma-separated, ordered), instantiates each provider, fans out queries, dedupes by `audio_url`, and swallows per-provider exceptions. Wrote 11 tests covering candidate parsing, GUID-first behaviour, factory selection, missing-credentials skip, dedup, exception containment. Registered new `RAGTIME_PODCAST_INDEXES`, `RAGTIME_FYYD_API_KEY`, `RAGTIME_PODCASTINDEX_API_KEY`, `RAGTIME_PODCASTINDEX_API_SECRET` in `settings.py`.

**Commit 4 — Convert download to agent + remove recovery layer.** Initially tried to keep these as two separate commits (matching the plan's enumeration) but discovered the rename `agents/recovery*` → `agents/download*` IS the recovery removal — splitting required compatibility shim modules just for one commit. Collapsed plan commits 4 + 5 into one logical commit, noted in the message. Renamed `agents/recovery.py`, `recovery_browser.py`, `recovery_deps.py`, `recovery_tools.py` → `agents/download.py`, `download_browser.py`, `download_deps.py`, `download_tools.py`; deleted `recovery_resume.py`. Renamed `RecoveryDeps` → `DownloadDeps` (added `title`/`show_name`/`guid`, dropped `error_type`/`http_status`/`step_name`/`error_message` since failure context is no longer flowed in). Renamed `RecoveryAgentResult` → `DownloadAgentResult` and added a `source` field (`"agent"` / `"fyyd"` / `"podcastindex"`). Added new `lookup_podcast_index` tool to `download_tools.py` — runs `episodes.podcast_indexes.lookup_episode_candidates` via `asyncio.to_thread`, falls back to deps' `title`/`show_name`/`guid` when the agent doesn't pass them. Rewrote the agent system prompt around the cascade: index lookup → page navigation + `find_audio_links` → click/intercept escalation. Rewrote `episodes/downloader.py` as a three-tier cascade with `DownloadResult` (frozen dataclass) on success and `DownloadFailed` (custom exception with structured fields) on full-cascade failure. Kept `start_step`/`complete_step`/`fail_step` calls intact for now — those become no-ops in the next commit; that lets test suites that simulate failures still trigger their assertions cleanly. Deleted `episodes/recovery.py`, `episodes/tests/test_recovery.py`, `episodes/tests/test_agent_resume.py`. Stripped the `step_failed.connect(handle_step_failure)` call out of `apps.py`. Removed `run_agent_recovery` and its helpers from `workflows.py`. Pruned `RecoveryAttemptAdmin`'s broken action and slimmed it to a read-only audit view (the model itself drops in commit 6). Updated `test_admin.py` (drop the recovery admin test classes), `test_agent_tools.py` (rename `RecoveryDeps` → `DownloadDeps`). Removed the legacy `RAGTIME_RECOVERY_*` settings in favour of `RAGTIME_DOWNLOAD_AGENT_API_KEY` / `_MODEL` / `_TIMEOUT`, with env-var fallback to the old keys for one transition release.

**Commit 6 — drop the four pipeline models + restructure the DBOS workflow.** Deleted `ProcessingRun`, `ProcessingStep`, `PipelineEvent`, `RecoveryAttempt` from `models.py`; generated migration `0023_drop_processing_pipeline_models`. Rewrote `episodes/workflows.py` from scratch: `process_episode` is now `for step_name, step_fn in _PIPELINE_DISPATCH: step_fn(episode_id)`, where `_PIPELINE_DISPATCH` is a list of `(status_value, @DBOS.step()-decorated function)` pairs — one explicit step per pipeline phase (`fetch_details_step_`, `download_step`, `transcribe_step`, `summarize_step`, `chunk_step`, `extract_step`, `resolve_step`, `embed_step`) plus a `_bootstrap_status` step that handles the QUEUED → first-step transition. Each step returns a frozen `StepOutput(episode_id, step_name)` dataclass; failures propagate up and DBOS records the exception class + args. Added `workflow_id_for(episode_id, attempt) -> str` for the deterministic `episode-<id>-run-<n>` ID — DBOS rejects duplicate IDs, replacing the dropped `unique_running_run_per_episode` partial index. Reduced `episodes/processing.py` to no-op shims so step modules don't have to be rewritten in this commit (future cleanup will inline + delete). Slimmed `events.py` to dataclasses + `classify_error` only (the persistence-side helpers and the `attempt_number`/`cached_data` fields are gone). Stripped the `step_completed`/`step_failed` Signal objects from `signals.py`. Updated `telemetry.py` to use a per-episode session ID rather than per-`ProcessingRun`. Cleaned up `admin.py` to drop the four model admins + the `NeedsHumanActionFilter` + the broken action references; switched the reprocess action to a simpler "set QUEUED + enqueue" flow (no more partial-unique-constraint dance, no more AWAITING_HUMAN handling). Updated `test_events.py` to keep only the `classify_error` tests; `test_admin.py` to drop the deleted admin pages, replace the awaiting-human assertion with a "metadata fields editable when failed" / "readonly when running" pair.

**Commit 7 — DBOS-backed Episode admin view.** Added a `_dbos_workflow_steps(episode_id)` helper that calls `DBOS.list_workflows`, filters by `workflow_id` prefix `episode-<id>-`, picks the most recent run, and pulls per-step rows via `DBOS.list_workflow_steps`. Wraps the whole thing in try/except → `[]` so admin keeps loading even when DBOS is offline. Registered a custom admin URL `<int:episode_id>/dbos-steps/` on `EpisodeAdmin.get_urls()`. Wrote `templates/admin/episodes/episode/dbos_steps.html` rendering function name + step ID + output + error in a table. Added a `dbos_steps_link` readonly field to the Episode change form so admins can jump straight to the workflow trace. Two tests cover the empty-state and populated rendering by mocking `_dbos_workflow_steps`.

**Commit 8 — env vars, wizard, docs.** Updated `.env.sample` to drop `RAGTIME_RECOVERY_*` and add `RAGTIME_DOWNLOAD_AGENT_*` + the four podcast-index variables. Replaced the "Recovery" section in `_configure_helpers.SYSTEMS` with two sections: "Download Agent" (Convention B — model string carries the provider, no separate `_PROVIDER` field; 1 secret + 2 non-secret) and "Podcast Indexes" (`RAGTIME_PODCAST_INDEXES` list + 3 API keys/secrets). Updated `core/tests/test_configure.py` — every wizard test had a hard-coded sequence of `mock_getpass`/`mock_input` side effects matching the systems list; rewrote each to add 3 new getpass calls (FYYD + podcastindex key + podcastindex secret) and adjust the input section count from "Recovery (3 fields)" to "Download Agent (model, timeout) + Podcast Indexes (PODCAST_INDEXES)". Updated `README.md` (replaced "Agent-based recovery" bullet with "Agent-driven download", clarified the Download row in the pipeline table, swapped "recovery layer" link wording for "the download-agent cascade", updated the Tech Stack bullet). Updated `doc/README.md`: replaced the entire "Recovery" subsection with a "Download cascade" subsection covering the three tiers, configuration via the new env vars, the two podcast indexes; flagged the recovery Excalidraw diagram as stale; updated the step-3 Download description to point at the new section; updated the workflow narrative ("step_failed signal" → "DBOS records the exception verbatim, plus DownloadFailed carries structured fields"). Wrote `doc/features/2026-04-28-download-agent-and-recovery-removal.md` with the standard Problem / Changes / Key parameters / Verification / Files modified structure. Wrote this transcript. Added a CHANGELOG entry under `## 2026-04-28` (which already exists from PR #107) with `### Added` (podcast indexes, download-agent), `### Changed` (download cascade, REQUIRED_FIELDS, DBOS workflow shape), `### Removed` (recovery layer, four pipeline models, three RAGTIME_RECOVERY_* env vars) sections, all marked **BREAKING** for the env-var renames and dropped models, with links to plan / feature / planning session / implementation session.

After each commit ran `uv run python manage.py test` to verify green. Final count: 336 passing tests (down from 351 before — net delete of recovery-specific tests + add of 11 podcast-index tests + 2 dbos-steps view tests + 2 fetch-details-guid tests).

### User

> /pr-create

### Assistant

Pushed the eight commits and opened PR #109 against `main` with a short summary referencing issue #108 and pointing at the plan, feature doc, and both session transcripts.

### User

> Push the changes to the PR, update the PR description and set it to "ready for review"

### Assistant

Pushed remaining commits, rewrote the PR body with the full implementation summary + commit list + a six-section test plan (one-time prereqs, reset+bootstrap, worker, submit, DBOS trace verification, admin view verification), and ran `gh pr ready 109`.

### User

> I'm seeing this error in the CI/CD test output: AssertionError: 'wget' not found in "BrowserType.launch: Executable doesn't exist…"

### Assistant

`test_wget_error_sets_failed` was written for the pre-cascade behaviour where wget failure went straight to `fail_step`. Under the new cascade, wget failure falls through to the agent which tries to launch Playwright — and CI doesn't run `playwright install chromium`, so it crashed. Renamed the test to `test_wget_error_falls_through_to_agent`, mocked `episodes.agents.download.run_download_agent` to return a `success=False` `DownloadAgentResult`, and asserted that the resulting `DownloadFailed` payload carries both `wget` and `agent` in `sources_tried`. Added `test_agent_recovers_after_wget_fails` covering the wget-fails-but-agent-succeeds path the old test never reached. Pushed `2e03606`.

### User

> In the issue referenced by this PR, in the "Verification" section, are those commands correct? Is that all that is needed? Will "docker compose down -v" delete the ragtime database?

### Assistant

Audited the verification block on issue #108 against the actual project requirements. Three real problems:

* `docker compose down -v` removes the `pgdata` named volume and therefore wipes the **MusicBrainz database too** (per `AGENTS.md`, `RAGTIME_MUSICBRAINZ_DB_*` defaults inherit from `RAGTIME_DB_*` so MB lives in the same Postgres container by default). Re-importing MB is a multi-GB / ~30+ minute job. Better: `manage.py dbreset --yes` which drops only the `ragtime` DB + the Qdrant collection.
* Missing prereqs: `manage.py load_entity_types` (resolver depends on EntityType rows), `manage.py createsuperuser` (admin login), `playwright install chromium` (download-agent browser path), a worker process (`uv run uvicorn ragtime.asgi:application`) running concurrently, and `dbos workflow list` to find the workflow ID before `dbos workflow steps <id>`.
* The 8-step claim was off by one — with the new shape there are 9 entries (`_bootstrap_status` + 8 pipeline phases).

Rewrote issue #108's Verification section with explicit one-time-prereqs / reset / worker / submit / verify-trace / verify-admin sections and a warning against `down -v`. Same rewrite applied to PR #109's Test plan in a follow-up turn so the two stayed in sync.

### User

> For the tests, in GitHub Actions, I can only see the test logs. Would there be a way to see test reports to improve the interpretation of the unit test results?

### Assistant

Outlined three escalating options: (A) JUnit XML via `unittest-xml-reporting` + `EnricoMi/publish-unit-test-result-action` for PR-check annotations; (B) coverage on top via Codecov or `cobertura-action`; (C) full pytest migration (overkill). Recommended (A) as the cheapest win.

### User

> No, let's leave this topic for a future PR.

### Assistant

Noted, leaving CI test reporting for a separate PR.

### User

> /pr-review-comments-process

### Assistant

Pulled the open review on PR #109 — a single self-review with three blocking issues:

1. **DBOS records failed pipeline steps as successful.** The step wrappers always return `StepOutput` after the legacy step body returns, but the legacy bodies signal failure by setting `Episode.status = FAILED` and returning normally. DBOS sees success.
2. **Deterministic workflow IDs declared but never applied.** `workflow_id_for()` was defined but `signals.queue_next_step` and the admin reprocess action both called `episode_queue.enqueue(...)` bare — DBOS assigned UUIDs and the admin's `episode-<id>-` prefix filter never matched.
3. **Agent-discovered audio URLs should replace stale failed URLs.** The downloader only saved `agent_result.audio_url` when `episode.audio_url` was empty; a stale URL that wget had failed on was never overwritten.

### User

> yes [implement all three]

### Assistant

Addressed all three in `4833851`:

* Added a typed `StepFailed` exception hierarchy (`FetchDetailsFailed`, `DownloadStepFailed`, …, `EmbedFailed`) in `episodes/workflows.py` and a `_raise_if_failed(episode_id, exc_cls)` helper. Each step wrapper refreshes the episode after the legacy body returns and raises the matching subclass when status is FAILED — DBOS records the exception class + message verbatim.
* Introduced `enqueue_episode(episode_id, from_step="")` that wraps `episode_queue.enqueue(...)` in `SetWorkflowID(workflow_id_for(episode_id, next_attempt(episode_id)))`. `next_attempt()` walks `DBOS.list_workflows()` to find the highest existing `episode-<id>-run-<n>` and returns `n+1` (defaults to 1 when DBOS isn't running). Both `signals.queue_next_step` and `EpisodeAdmin._execute_reprocess` now route through it.
* Changed the downloader guard from `not episode.audio_url` to `agent_result.audio_url != episode.audio_url` so a stale URL gets overwritten by an agent-discovered enclosure.
* New `episodes/tests/test_workflows.py` (8 tests) covering `workflow_id_for`, `next_attempt` (DBOS-unavailable / no-prior-runs / max-of-existing+1 with cross-episode IDs filtered out), `_raise_if_failed` no-op vs typed-raise paths, and the StepFailed subclass step_name attribute. `test_signals.py` and `test_download.py` updated for the new shapes. Posted a single consolidated reply on the PR thread referencing each issue + its resolution + its test coverage.

### User

> Re: 3 -> we can remove the recovery documentation and diagrams since they are no longer relevant and update the documentation for the "Fetch Details" and "Download" pipeline steps. […] Related question: how do we avoid the Download agent to continuously retry if it cannot download the episode's audio MP3?

### Assistant

Deleted `doc/architecture/ragtime-recovery.{excalidraw,svg}` and `doc/architecture/ragtime-processing-pipeline-with-recovery.{excalidraw,svg}` (committed in `9a43f69`). Folded the standalone "Download cascade" section in `doc/README.md` into the step-3 description so the per-step doc is the single source of truth. Expanded the step-2 Fetch Details doc with the EpisodeDetails schema, the orchestrator's responsibilities, and why audio_url is no longer required. Updated `AGENTS.md` to reference the deterministic DBOS workflow ID approach instead of the dropped `unique_running_run_per_episode` constraint.

For the retry-loop question: explained the three layers of cap that already exist — `UsageLimits(request_limit=30)` per agent run, `RAGTIME_DOWNLOAD_AGENT_TIMEOUT` (default 120s) wall-clock, and a single attempt per pipeline run (no built-in retry loop around the agent — failure raises `DownloadFailed` and the episode goes to `failed`; only an admin reprocess action retries). User confirmed those caps were sufficient; no new knobs needed.

### User

> Can you create issues for the two points that you raised above with enough context and a reference to the current issue we are working on in this PR?

### Assistant

Filed #110 (typed StepFailed exceptions break the dbos CLI's deserializer because `episodes.workflows` isn't on the CLI's import path) and #111 (download agent's index-candidate matching is too strict for non-English shows — `_show_name(episode)` falls back to the URL host so fyyd's "Zeitzeichen" never matches "www.ardsounds.de"). Both reference PR #109 / issue #108.

### User

> I've tested with one episode and […] empty list. […] what env var […] postgres password […]

### Assistant

Walked through diagnosing the empty admin-page problem. First hypothesis: episode 1 was submitted before `4833851`'s deterministic-IDs commit and had a UUID workflow ID. User ran `dbos workflow list` (after we worked out that the CLI takes `--sys-db-url` not `DBOS_SYSTEM_DATABASE_URL`) and the workflow had the new `episode-1-run-1` ID — so the prefix filter should have matched. Then ran `dbos workflow steps episode-1-run-1` and got back three step records as expected.

Real bug surfaced from the admin: `DBOS.list_workflows()` and `DBOS.list_workflow_steps()` return TypedDicts, not objects. The helper used `getattr(record, "workflow_id", "")` which silently returned the default for dicts — so the prefix filter never matched, candidates was `[]`, and the helper returned `[]`. Fixed in `168eba6` with a new `_dbos_field(record, name, default)` helper that uses `dict.get()` for TypedDicts and falls back to `getattr` for forward compatibility. Regression test added.

### User

> I can see now […] in the ERROR column this red string "gAS…" What is that?

### Assistant

That's the base64-encoded pickled `DownloadStepFailed` exception — DBOS persists step output / error as pickle bytes and `list_workflow_steps()` returns the wire form rather than the unpickled object. Two-part fix in `9ff6719`:

* Added `StepFailed.__reduce__` returning `(cls, (episode_id, error_message))` so pickle round-trips cleanly. The default `Exception.__reduce__` puts only the formatted message in `self.args` so `pickle.loads` calls `cls(formatted_message)` and raises TypeError against the two-arg `__init__`.
* New `_decode_dbos_payload(value)` helper in `admin.py`: when the value looks like a base64-encoded pickle (starts with `gAS` — protocol-4 magic), base64-decodes + `pickle.loads` and returns `str(obj)`. Falls back to the raw value on decode failure (so legacy rows pickled before the `__reduce__` fix still render). Both `output` and `error` columns route through it.

Noted that the standalone CLI still can't unpickle (no `episodes` module on its path) — that's #110.

### User

> Do we need to add a comment about this on issue #110? […] Or update the issue description?

### Assistant

Edited issue #110's body to lead with a "Status" section showing the partial fix (`9ff6719` adds in-process unpickle) and what remains (cross-process portability for the standalone CLI).

### User

> If I reprocess and episode, it seems that from the "DBOS workflow: View workflow steps" Django admin link I can only see *one* workflow.

### Assistant

The helper sorted by `created_at` and returned only the latest run. Restructured to mirror the old `ProcessingRunInlineForEpisode` + `ProcessingStepInline` UX, in `e53f055`:

* New `_dbos_workflow_runs(episode_id)` returns every `episode-<id>-run-<n>` workflow newest-first, each carrying its own `steps` list looked up via a new `_step_rows_for_workflow` helper. The existing `_dbos_workflow_steps` is kept as a thin shim returning the latest run's steps for callers that still want the single-run shape. New `_epoch_ms_to_datetime` helper for display.
* Template restructured to render one section per run with the workflow ID, a colour-coded status pill (SUCCESS green, ERROR red, PENDING/ENQUEUED yellow, CANCELLED grey), started / updated / queue metadata, and the per-step table. Plural-aware run count in the header.
* Change-form link relabelled "View workflow runs" (was "View workflow steps").

### User

> For one of the episodes, I can see this error […]: resolving failed for episode 1: deadlock detected […]

### Assistant

Real bug in the resolver, predating this PR. `_acquire_name_locks` sorted names *within* one entity type but the locking happened *inside* the per-type loop, so two parallel resolvers iterating entity types in different insertion orders (driven by the LLM's output order) deadlocked when they shared names across types. Fix in `d147495`: hoisted the lock acquisition out of the per-type loop. `_acquire_name_locks` now takes an iterable of `(entity_type_id, name)` tuples spanning **all** types touched by the resolve, and sorts globally before acquiring. Pre-resolved every `EntityType` referenced by the aggregated chunks before opening the transaction so unknown keys still log a warning each. Existing resolver tests still pass.

### User

> Even after some time has passed after processing several Episodes, there is still no Wikidata ID assigned to any of the resolved entities.

### Assistant

Found and fixed the most critical bug of the PR. From DBOS source (`_core.py:839-853`): when `start_workflow` (which `Queue.enqueue` calls) is invoked from inside a workflow/step, DBOS keys its operation log on `(parent_workflow_id, parent_workflow_fid, target_func_name)`. Inside a `@DBOS.step()` body every enqueue call shares the step's `function_id`, so only the first enqueue per `(step, target_func)` pair runs and subsequent calls return the first call's handle without dispatching anything. The resolver was enqueueing N wikidata workflows from inside `resolve_step` — only one was actually starting, and once that one was recorded as terminal, subsequent runs replayed the same handle without enqueueing.

Fix in `13b5ad1`: hoisted the enqueue to workflow context.

* `resolver.resolve_entities` now returns `list[int]` (entity IDs to enrich) instead of trying to enqueue them itself. `_enqueue_enrichment` deleted.
* New `ResolveStepOutput(StepOutput)` dataclass in `workflows.py` carries `entity_ids_to_enrich: tuple[int, ...]`. `resolve_step` returns it; `process_episode` (the `@DBOS.workflow()`) captures the tuple during dispatch and runs the enqueue loop after the pipeline completes — workflow context, where DBOS lets enqueue actually do its job.
* Resolver tests refactored: `setUp` now patches `resolver.resolve_entities` with a `side_effect` that captures the return value into `self._last_enqueued_ids`, and three call sites updated to read that. New `test_workflows.py` cases pin the `ResolveStepOutput` contract.

### User

> I executed "uv run python manage.py enrich_entities" […] Did you create the management command "enrich_entities" for this PR or was it existing?

### Assistant

Pre-existing — added in PR `feature/musicbrainz-resolution` on April 27 (`8a5ff7b`). I noted that the "Failed to start admin server: Address already in use" warning is harmless (uvicorn already grabbed DBOS's admin port), and walked through the diagnostic queries to verify the queue was draining.

### User

> psql -c "…" […]
> ENQUEUED |    77
> PENDING  |     1
> SUCCESS  |   149
> So it seems it is draining

### Assistant

Confirmed: with concurrency=1 on the wikidata queue, 77 entries waiting + 1 in flight + 149 done is the expected shape. Re-queries would show ENQUEUED draining toward 0 and SUCCESS climbing to 227.

### User

> I can also see wikidata ids assigned in the Django admin UI […] [some time later:] This is now stuck and I am seeing these errors in the logs: "MB → Wikidata link lookup failed for work/d59b1f19… psycopg.errors.UndefinedTable: relation 'l_work_url' does not exist"

### Assistant

Real bug in the local MB→Wikidata lookup. MusicBrainz names entity-relationship tables `l_<a>_<b>` with the two entity types in alphabetical order, and the matching `entity0` / `entity1` columns follow that same ordering. For most types `<entity> < url` so the table is `l_<entity>_url` with `entity0=<entity>`, `entity1=url`. But `url < work` alphabetically — MB stores work-URL relationships in `l_url_work` with `entity0=url`, `entity1=work`. The hard-coded `l_work_url` reference raised `UndefinedTable` for every work entity.

Fix in `872aa9c`: every `_TABLE_CONFIG` entry now declares `link_main_col` / `link_url_col` explicitly. The `work` entry uses `l_url_work` with `link_main_col="entity1"`, `link_url_col="entity0"` (everyone else stays `entity0` / `entity1`). `get_wikidata_qid` reads those columns from the config and threads them into the JOIN, defaulting to `entity0` / `entity1` for forward compatibility. Verified against the live MB schema: `to_regclass('musicbrainz.l_url_work')` returned the table; `to_regclass('musicbrainz.l_work_url')` returned NULL.

### User

> I am getting an error when I try to re-enqueue entities for enrichment […] cannot schedule new futures after shutdown

### Assistant

Cosmetic — the enqueue succeeded (147 entities). The error is a shutdown race inside the management command's own DBOS instance: `enrich_entities` is in `_DBOS_COMMANDS`, so it calls `DBOS.launch()` and becomes a worker. As it exits, its dispatcher tries to dequeue an entry and submit it to the local thread pool — which has already been torn down by Python's atexit handler. uvicorn (running concurrently) picks up all 147 entries.

### User

> yes, file an issue with the details

### Assistant

Filed #113 — `manage.py enrich_entities` should be a DBOS client, not a worker. Three options laid out (split `_DBOS_COMMANDS` into `is_worker` + `is_client` so client commands skip `launch()`, brief drain loop, document-and-ignore). Recommended option 1. Acceptance criteria explicit, plus a note that `submit_episode` likely has the same issue.

### User

> Manual testing is done!

### Assistant

Wrote and committed this transcript. PR #109 is ready to merge — five follow-up issues filed (#110 CLI deserialization, #111 agent matching, #112 inline Wikidata resolution, #113 DBOS client mode, plus the in-line ARD test issue noted earlier). 351 tests passing.

## Follow-up issues filed during this session

| # | Title | Origin |
|---|-------|--------|
| #110 | Replace typed StepFailed exceptions with serializable failure objects so the dbos CLI can render them | CLI couldn't import `episodes.workflows` to unpickle |
| #111 | Tighten the download agent's index-candidate matching heuristic for non-English shows | Agent rejected fyyd matches for ARD episodes |
| #112 | Resolve Wikidata QID inline from MusicBrainz during foreground entity resolution | "Why wait for the background queue when MB has the link locally?" |
| #113 | manage.py enrich_entities should be a DBOS client, not a worker | Shutdown race + queue contention with uvicorn |

## Final commit list (PR #109)

| SHA | Description |
|-----|-------------|
| `8d33162` | Plan + planning session transcript |
| `984a4f8` | Episode.guid + fetch_details extension + relax REQUIRED_FIELDS |
| `9dc7a75` | podcast_indexes provider abstraction (fyyd, podcastindex.org) |
| `239fcd6` | Convert Download to Pydantic AI agent + remove recovery layer |
| `7f186ff` | Drop ProcessingRun/ProcessingStep/PipelineEvent + restructure DBOS workflow |
| `c9a55d5` | DBOS-backed Episode admin view |
| `fc7664d` | env vars, configure wizard, README, doc/README, CHANGELOG, feature doc + impl session |
| `9a43f69` | Remove obsolete recovery diagrams + consolidate Fetch Details/Download docs |
| `2e03606` | Fix CI: mock the download agent in test_download |
| `4833851` | Address PR review: raise into DBOS, dedup workflow IDs, refresh stale audio_url |
| `2e03606` … `872aa9c` | (further follow-ups during manual testing — see commit log) |
| `168eba6` | Fix admin DBOS view returning empty list against TypedDict records |
| `9ff6719` | Render DBOS step output / error in admin instead of pickle wire format |
| `e53f055` | Show every workflow run in the Episode admin DBOS view |
| `d147495` | Fix resolver deadlock when parallel episodes share entity names across types |
| `13b5ad1` | Fix Wikidata enrichment never running — enqueue from workflow not step |
| `872aa9c` | Fix MB→Wikidata lookup for work entities — table is l_url_work, not l_work_url |
