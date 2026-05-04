# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## 2026-05-04

### Added

- `Episode.show_name` `CharField` (max 255, blank default) populated by the fetch_details agent from `<meta property="og:site_name">`, `<meta name="application-name">`, RSS `<channel><title>`, JSON-LD `isPartOf.name` / `partOfSeries.name`, or the visible publisher heading. Persisted only when the agent's extracted value is non-empty (a re-run that fails to extract leaves a previously-good value or admin edit in place). Migration `0025_episode_show_name`. No backfill — pre-prod data freedom per `feedback_reembed_ok_preprod.md`.
- `EpisodeCandidate.published_at` (`date | None`) on the podcast-aggregator dataclass. Each aggregator now extracts a publication date from its native field (`pubdate` for fyyd, `releaseDate` for iTunes, `datePublished` epoch seconds for podcastindex) and logs + returns `None` on missing or malformed input rather than dropping the candidate. Surfaced through `DownloadDeps.published_at` and `IndexCandidate.published_at` so the download agent sees per-episode and per-candidate dates.

### Changed

- Download agent's `_show_name(episode)` cascade now prefers `episode.show_name`, falling back to the URL host only as a defense-in-depth signal. The agent prompt is updated to detect hostname-shaped `Show` values (contains `.` and no spaces) and switch to a `(title, published_at)` match with ±1 day tolerance instead of requiring an exact `show_name` string match. Real broadcast titles still use the existing show-plus-title path. Closes #111 — [plan](doc/plans/2026-05-04-download-show-name-fix.md), [feature](doc/features/2026-05-04-download-show-name-fix.md), [planning session](doc/sessions/2026-05-04-download-show-name-fix-planning-session.md), [implementation session](doc/sessions/2026-05-04-download-show-name-fix-implementation-session.md)
- AGENTS.md and the Feature PR Documentation Bundle AI check now recognize **agent-orchestrated sessions**. When a parallel implementation agent is launched from a parent Claude Code session (e.g. under Conductor) and has no direct user-to-implementation-agent messages, the transcript may use `### Parent agent (orchestrator)` headings *instead of* `### User`, provided the parent-agent's launching prompt is reproduced verbatim. The transcript must declare the session as agent-orchestrated at the top of `## Detailed conversation`. Same verbatim rule applies — summarized parent prompts are still rejected. This is a policy clarification only; no code changes.
- AI checks workflow now renders non-applicable rules as gray "skipped" icons instead of green "pass". `list_ai_checks.py` evaluates each rule's `paths:` frontmatter against `git diff --name-only $BASE_REF...HEAD` and emits `applies: bool` per matrix include; `.github/workflows/ai-checks.yml` gates each `check` shard on `if: ${{ ... && matrix.applies }}`, so non-applicable shards skip at the GHA level — no runner spin-up, no model call, no token cost. Four rules gain `paths:` frontmatter (`pipeline-step-sync`, `asgi-wsgi-scott`, `qdrant-payload-slim`, `entity-creation-race-safety`); the other five remain semantic. The driver's verdict tool drops `skip` from its enum: semantic non-applicability is now `pass` with `summary: "Rule does not apply."` and a one-line `details` explanation. Closes #124 — [plan](doc/plans/2026-05-04-ai-checks-skipped.md), [feature](doc/features/2026-05-04-ai-checks-skipped.md), [planning session](doc/sessions/2026-05-04-ai-checks-skipped-planning-session.md), [implementation session](doc/sessions/2026-05-04-ai-checks-skipped-implementation-session.md)
- **BREAKING** — `StepFailed`-derived exceptions now pickle as `RuntimeError(message)` rather than as their typed subclass. Pre-fix workflow rows in the DBOS `dbos.workflow_status` table will not deserialize to readable text — the Episode admin's "View workflow steps" page will show a base64 preview only. Action required: reprocess affected episodes (which produces fresh, portable pickles) or clear the workflow_status table in dev environments. No production impact since this project is pre-prod. See PR #129 for details.

### Fixed

- DBOS step errors now deserialize cleanly outside the Django process. `StepFailed.__reduce__` returns `(RuntimeError, (str(self),))` so the on-the-wire pickle is a plain stdlib `RuntimeError` — the standalone `dbos workflow steps` CLI (and DBOS Conductor) can rehydrate it without importing `episodes.workflows`, eliminating the `Warning: exception object could not be deserialized … No module named 'episodes'` noise. Worker-side semantics are unchanged: `raise DownloadStepFailed(...)` still matches `except StepFailed`. The Episode admin's `_decode_dbos_payload()` fallback for legacy rows whose typed-class wire format can no longer be rehydrated now renders `<could not deserialize: <80-char preview>>` instead of the raw b64 blob. Closes #110 — [plan](doc/plans/2026-05-04-stepfailed-portable-pickle.md), [feature](doc/features/2026-05-04-stepfailed-portable-pickle.md), [planning session](doc/sessions/2026-05-04-stepfailed-portable-pickle-planning-session.md), [implementation session](doc/sessions/2026-05-04-stepfailed-portable-pickle-implementation-session.md)
- DBOS-backed management commands (`manage.py submit_episode`, `manage.py enrich_entities`) no longer race the uvicorn worker. `episodes/apps.py:_init_dbos` now distinguishes worker entrypoints (`uvicorn`, `runserver`) from client commands; clients call `DBOS.listen_queues([])` immediately before `DBOS.launch()` so their dispatcher iterates over zero application queues. Eliminates the `Contention detected in queue thread for wikidata_enrichment` warning and the `cannot schedule new futures after shutdown` shutdown race when running a backfill while uvicorn is consuming the queue. uvicorn remains the only process that dequeues `episode_pipeline` and `wikidata_enrichment`. Pure "skip launch()" doesn't work — `DBOS._sys_db` is created inside `launch()` and `Queue.enqueue` requires it — so the fix is `listen_queues([])` plus `launch()` rather than no launch. Closes #113 — [plan](doc/plans/2026-05-04-dbos-enqueue-only-clients.md), [feature](doc/features/2026-05-04-dbos-enqueue-only-clients.md), [planning session](doc/sessions/2026-05-04-dbos-enqueue-only-clients-planning-session.md), [implementation session](doc/sessions/2026-05-04-dbos-enqueue-only-clients-implementation-session.md)

## 2026-05-01

### Added

- Self-hosted AI checks GitHub Action with provider-neutral routing via LiteLLM. Replaces Continue.dev (#117) as the runner for the rule files migrated from `.continue/checks/` → `.ai-checks/` (9 files, frontmatter + body unchanged). New `.github/workflows/ai-checks.yml` runs a `list` job that scans `.ai-checks/*.md` and emits a JSON matrix, then a `check` job that fans out one matrix shard per rule (`fail-fast: false`, job name `AI Check: <rule name>`, so each rule appears as its own PR status row — matching the Continue UX). New `.github/scripts/list_ai_checks.py` (matrix emitter) and `.github/scripts/run_ai_check.py` (per-rule driver: parses frontmatter, reads `git diff $BASE_REF...HEAD`, optional `paths:` glob short-circuits to `skip`, calls LiteLLM with a `report_verdict` function — `pass`/`fail`/`skip` + summary + details — and writes a Markdown summary to `$GITHUB_STEP_SUMMARY`; exits 1 on `fail`). `AI_CHECK_MODEL` is a LiteLLM model string carrying the provider as a prefix (`openai/gpt-4o-mini` (default), `anthropic/claude-sonnet-4-6`, `gemini/gemini-2.0-flash`); LiteLLM auto-reads each provider's canonical env var (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`). Switching providers is a one-line repo-variable change plus the matching secret — no driver edits. Closes #121 — [plan](doc/plans/2026-05-01-ai-checks-action.md), [feature](doc/features/2026-05-01-ai-checks-action.md), [planning session](doc/sessions/2026-05-01-ai-checks-action-planning-session.md), [implementation session](doc/sessions/2026-05-01-ai-checks-action-implementation-session.md)
- Structured CI test reporting. `PostgresTestRunner` now emits a single combined JUnit XML to `test-results/junit.xml` when `JUNIT_XML_OUTPUT=1`, leaving local `manage.py test` invocations unchanged. The CI workflow publishes the XML via `EnricoMi/publish-unit-test-result-action@v2` (sticky PR comment when results change vs base, `Unit Test Results` Check Run with diff annotations, rich workflow-run summary). New dev dependency: `unittest-xml-reporting`. Job-scoped `permissions:` block grants the test job `pull-requests: write` and `checks: write`. Preparatory work for the agent-evaluation framework (#115), whose results will live alongside this Check under a separate `check_name` — [plan](doc/plans/2026-05-01-ci-test-visibility.md), [feature](doc/features/2026-05-01-ci-test-visibility.md), [planning session](doc/sessions/2026-05-01-ci-test-visibility-planning-session.md), [implementation session](doc/sessions/2026-05-01-ci-test-visibility-implementation-session.md)

### Changed

- CI test step verbosity dropped from `--verbosity 2` to `--verbosity 1`. The structured XML now carries the per-test detail; the GitHub Actions log only needs to surface unexpected failures.

### Removed

- `.continue/checks/` directory and Continue.dev integration. The 9 rule files migrate verbatim to `.ai-checks/` and run through the self-hosted workflow above. The motivation is provider-account consolidation — RAGtime already pays for OpenAI and Anthropic credits, and a third billable account is one more thing to top up, monitor, and rotate. (As context on the failing-check state that prompted this: credits were added to the Continue.dev account during initial debugging, but the GitHub checks still failed to run — moving off a separately-billed runner is the right call regardless of root cause.) Adopting Continue.dev before RAGtime had its own eval infrastructure was premature; revisiting it once #115's eval framework lands is on the table.

## 2026-04-29

### Added

- **BREAKING** — Fetch Details investigator agent with cross-linking tools, outcome taxonomy, and per-run history. The Fetch Details step is now a Pydantic AI agent loop with three keyless tools — `fetch_url` (httpx + BeautifulSoup), `search_apple_podcasts` (iTunes Search API), `search_fyyd` (fyyd.de) — that classify the submitted URL as canonical / aggregator / unknown and cross-link between publisher canonical pages and aggregator entries when extraction is incomplete. The agent emits a wrapped `FetchDetailsOutput { details, report, concise }`: `details` covers all episode-level facts including new `audio_format`, `country`, `canonical_url`, `source_kind`, `aggregator_provider`; `report` carries `attempted_sources`, discovery / cross-link booleans, `extraction_confidence`, free-text `narrative`, and `hints_for_next_step`; `concise` carries the 5-value `outcome` enum (`ok | partial | not_a_podcast_episode | unreachable | extraction_failed`) and a ≤140-char summary. New `FetchDetailsRun` table persists every run's full structured output, auto-captured tool-call trace, Pydantic AI usage dict, and DBOS workflow ID — `run_index` increments per episode on re-run. `Episode` gains `canonical_url`, `source_kind` (TextChoices), `aggregator_provider`, `audio_format`, `country`; `scraped_html` is dropped (HTML now lives per-tool-call on the run rows). Single migration `0024_fetch_details_cross_linking`. New `EpisodeAdmin` "Source" fieldset + latest-run summary block + inline runs table; new `FetchDetailsRunAdmin` with collapsible Concise / Report / Details / Tool calls / Raw payloads sections — [plan](doc/plans/2026-04-29-fetch-details-cross-linking.md), [feature](doc/features/2026-04-29-fetch-details-cross-linking.md), [planning session](doc/sessions/2026-04-29-fetch-details-cross-linking-planning-session.md), [implementation session](doc/sessions/2026-04-29-fetch-details-cross-linking-implementation-session.md)

### Changed

- **BREAKING** — Renamed `episodes/podcast_indexes/` → `episodes/podcast_aggregators/` with `PodcastIndex` ABC → `PodcastAggregator`. New `ItunesAggregator` (Apple Podcasts via the keyless iTunes Search API) joins fyyd and podcastindex.org. Env var `RAGTIME_PODCAST_INDEXES` → `RAGTIME_PODCAST_AGGREGATORS`; `apple_podcasts` (alias `itunes`) joins `fyyd` and `podcastindex` as recognized providers. The Download agent's `lookup_podcast_index` tool now consults the renamed package. `.env.sample` and `core/management/commands/configure.py` updated. Pre-prod, no fallback. `EpisodeCandidate.source_index` field name preserved to minimize churn.
- **BREAKING** — Fetch Details orchestrator rewritten. Agent output is authoritative — Episode columns are overwritten directly, no more empty-field-only merge or fast-path skip. The 30 KB HTML fetch + clean now lives inside the `fetch_url` tool rather than the orchestrator. The 5-outcome enum on `FetchDetailsRun` discriminates failure modes; only `Episode.Status.FAILED` is reused — no new Status values. `processing.py` shim calls dropped from the new step (module untouched — other steps still use it). The `@DBOS.step()` wrapper reads `DBOS.workflow_id` and passes it into the orchestrator so the agent module stays DBOS-import-free; `_raise_if_failed` typed-exception pattern preserved.
- `README.md` and `doc/README.md` updated: pipeline-summary cell for Fetch Details rewritten, Fetch Details section in `doc/README.md` rewritten with the agent / tools / output schema / outcome table, podcast-aggregators section renamed.

### Removed

- **BREAKING** — Dropped `Episode.scraped_html`. Per-tool-call HTML excerpts (capped ~5 KB) now live in `FetchDetailsRun.tool_calls_json`.

## 2026-04-28

### Added

- **BREAKING** — Pydantic AI download agent with podcast-index lookup and Playwright tooling. New `episodes/podcast_indexes/` package (`PodcastIndex` ABC + `EpisodeCandidate` dataclass + fyyd.de + podcastindex.org clients + a fan-out factory that dedupes by `audio_url`). New `episodes/agents/download.py` (renamed from `agents/recovery.py`) with a `lookup_podcast_index` tool added alongside the existing browser tools. `episodes/downloader.py` rewritten as a three-tier cascade: `wget` on `episode.audio_url` → download agent → structured `DownloadFailed(episode_id, sources_tried, wget_error, agent_message)` exception that DBOS records verbatim. Returns a typed `DownloadResult` on success. New `Episode.guid` field (`CharField`, blank), extracted by the fetch_details agent, used as a hint by `lookup_podcast_index`. New env vars: `RAGTIME_DOWNLOAD_AGENT_API_KEY` / `_MODEL` / `_TIMEOUT` (with one-release env-var fallback to the deprecated `RAGTIME_RECOVERY_AGENT_*` keys), `RAGTIME_PODCAST_INDEXES` (comma-separated ordered list, empty = no index lookup), `RAGTIME_FYYD_API_KEY` (optional; raises rate limits), `RAGTIME_PODCASTINDEX_API_KEY` + `_SECRET` (required when `podcastindex` is configured). New DBOS-backed Episode admin view at `<id>/dbos-steps/` reads `DBOS.list_workflow_steps()` and renders per-step `function_name` / output / error in a table; the Episode change form gains a "View workflow steps" link in the main fieldset. 13 new tests (11 podcast-indexes + 2 admin DBOS-steps) — [plan](doc/plans/2026-04-28-download-agent-and-recovery-removal.md), [feature](doc/features/2026-04-28-download-agent-and-recovery-removal.md), [planning session](doc/sessions/2026-04-28-download-agent-and-recovery-removal-planning-session.md), [implementation session](doc/sessions/2026-04-28-download-agent-and-recovery-removal-implementation-session.md)

### Changed

- **BREAKING** — Relax `fetch_details_step.REQUIRED_FIELDS` to `("title",)` only. `audio_url` is no longer required for fetch-details to advance — the download agent now owns audio-URL discovery for cases where fetch-details could only recover a title. The fetch_details agent's `EpisodeDetails` schema and system prompt also gain a `guid` field. Migration `0022_add_episode_guid` adds the `Episode.guid` CharField.
- **BREAKING** — DBOS workflow restructured. `process_episode` now declares one explicit `@DBOS.step()` per pipeline phase (`fetch_details_step_`, `download_step`, `transcribe_step`, `summarize_step`, `chunk_step`, `extract_step`, `resolve_step`, `embed_step`) plus a `_bootstrap_status` step. No more dynamic-dispatch `importlib` lookup, no more bookkeeping steps (`create_run_step`, `is_run_still_active`, `did_step_complete`, `mark_run_failed`, `get_pending_resume_step`, `mark_queued`). `dbos workflow steps <id>` (and the new admin view) mirrors `PIPELINE_STEPS` exactly. Successful steps return a typed `StepOutput`; failures propagate up and DBOS records the exception class + args. Deterministic per-episode workflow IDs (`episode-<id>-run-<n>`) replace the dropped `unique_running_run_per_episode` partial index — DBOS rejects duplicate IDs.
- The `manage.py configure` wizard's "Recovery" section is replaced with two sections: "Download Agent" (Convention B — provider in the model string prefix; 1 secret + 2 non-secret fields) and "Podcast Indexes" (`RAGTIME_PODCAST_INDEXES` list + 3 API keys/secrets). `.env.sample`, `README.md` (pipeline summary table + tech-stack bullet), and `doc/README.md` (step-3 Download description + new "Download cascade" section) updated. The `doc/architecture/ragtime-recovery.svg` Excalidraw diagram is now stale and is flagged in `doc/README.md` for manual regeneration.

### Removed

- **BREAKING** — Recovery layer deleted. Removed `episodes/recovery.py` (the `AgentStrategy` / `HumanEscalationStrategy` chain and the `step_failed` signal handler), `episodes/agents/recovery_resume.py`, the `step_completed` / `step_failed` Django signals, the `run_agent_recovery` DBOS workflow + helpers, the `RecoveryAttemptAdmin.retry_agent_recovery` action, and the `RAGTIME_RECOVERY_AGENT_ENABLED` / `RAGTIME_RECOVERY_AGENT_API_KEY` / `RAGTIME_RECOVERY_AGENT_MODEL` / `RAGTIME_RECOVERY_AGENT_TIMEOUT` settings. The download agent's three-tier cascade (cheap `wget` → agent → structured exception) covers what the recovery layer used to do, with the agent itself running on every download attempt that needs it rather than only after a `fail_step` signal.
- **BREAKING** — Dropped `ProcessingRun`, `ProcessingStep`, `PipelineEvent`, `RecoveryAttempt` models. Migration `0023_drop_processing_pipeline_models` removes the four tables. DBOS owns workflow state; `Episode.status` + `Episode.error_message` carry the user-facing summary. Pre-prod data is not preserved through this migration — a full Postgres regen + re-ingest is the supported upgrade path. `episodes/processing.py` is reduced to no-op shims so step modules don't have to be rewritten in this PR; future cleanup will inline & delete.

- **BREAKING** — Rename pipeline step `Scrape` → `Fetch Details` and migrate it to a Pydantic AI agent. Status enum value `scraping` → `fetching_details` (data migration `0021_rename_scraping_to_fetching_details` rewrites every persisted literal in `Episode.status`, `ProcessingStep.step_name`, `PipelineEvent.step_name`, `ProcessingRun.resumed_from_step`). Files renamed: `episodes/scraper.py` → `episodes/fetch_details_step.py` (function `scrape_episode` → `fetch_episode_details`), `episodes/agents/{agent,browser,deps,tools,resume}.py` → `recovery_*.py` (recovery agent files marked transitional ahead of deletion in a future PR). New `episodes/agents/fetch_details.py` (Pydantic AI agent with `EpisodeDetails` output model, ISO-639-1 + date validators) and `episodes/agents/_model.py` (shared `build_model(model_string, api_key)` helper used by both fetch_details and the recovery agent). Step orchestrator delegates the LLM call to the agent via `asyncio.run`; preserves fast-path skip when required fields are pre-filled, empty-field-only merge, save-before-fail-step ordering. `get_scraping_provider` deleted from `episodes/providers/factory.py`. Convention B env vars: `RAGTIME_SCRAPING_PROVIDER` removed, `RAGTIME_SCRAPING_MODEL` → `RAGTIME_FETCH_DETAILS_MODEL=openai:gpt-4.1-mini` (provider encoded in model string prefix), `RAGTIME_SCRAPING_API_KEY` → `RAGTIME_FETCH_DETAILS_API_KEY`. Configure wizard skips writing `_PROVIDER` for Convention B subsystems while continuing to share the API key across the LLM group. README, AGENTS.md, doc/README.md updated. Excalidraw diagrams in `doc/architecture/` flagged for manual update — [plan](doc/plans/2026-04-28-fetch-details-agent.md), [feature](doc/features/2026-04-28-fetch-details-agent.md), [planning session](doc/sessions/2026-04-28-fetch-details-agent-planning-session.md), [implementation session](doc/sessions/2026-04-28-fetch-details-agent-implementation-session.md)

## 2026-04-27

### Changed

- Foreground entity resolution switches from Wikidata API to local MusicBrainz Postgres database. New `episodes/musicbrainz.py` (raw psycopg via `psycopg_pool`) does sub-millisecond name → MBID lookups (case-insensitive against main + alias tables) and resolves MBID → Wikidata Q-ID via `l_<entity>_url` external links. Wikidata enrichment moves to a singleton background DBOS queue (`concurrency=1`) — `episodes/enrichment.py` — that backfills `Entity.wikidata_id` per entity, deduplicated globally so common names ("Django Reinhardt") only get enriched once. Foreground never calls Wikidata; episodes reach `READY` as soon as embedding finishes. Adds 8 mappings in `episodes/initial_entity_types.yaml` (musician/musical_group/album/composed_musical_work/music_venue/record_label/city/country); 6 types without MB equivalents (year/role/instrument/genre/recording_session/historical_period) skip MB and go straight to background Wikidata enrichment.
- Race-safe foreground resolver — replaces all `Entity.objects.create` with `get_or_create`, wraps candidate creation in a sorted Postgres transaction-scoped `pg_advisory_xact_lock` per `(entity_type, name)` (no deadlocks between resolvers that share names), plus an `IntegrityError` retry as defense-in-depth. Addresses the cross-episode `unique_entity_type_name` violation flagged by external review.
- Episode-pipeline parallelism via a new `episode_pipeline` DBOS queue with `concurrency=settings.RAGTIME_EPISODE_CONCURRENCY` (default 4). `episodes/signals.py` and `episodes/admin.py` switch from `DBOS.start_workflow` to `episode_queue.enqueue`. Adds `Episode.Status.QUEUED` between `PENDING` and `SCRAPING` so episodes waiting for a worker slot are visibly distinct from "freshly submitted" or "stuck". `workflows.create_run_step` transitions `QUEUED → from_step` (or first PIPELINE_STEP) when a worker picks the workflow up.
- Same-episode workflow dedup — partial unique constraint `unique_running_run_per_episode` (`ProcessingRun(episode_id) WHERE status='running'`) enforces "at most one active run per episode" at the DB level. `episodes/processing.get_active_run` switches from `.first()` to `.get()` so duplicates raise loudly rather than silently picking one.
- Slim Qdrant payload + Postgres-side hydration. Qdrant now stores only `chunk_id` + `episode_id` + `language` + `entity_ids`; everything Scott displays (episode title, urls, timestamps, chunk text, entity names, MBIDs, Wikidata IDs) is hydrated at search time from Postgres via one query keyed on the returned chunk_ids. Single source of truth — title edits flow through immediately, background Wikidata enrichment writes only Postgres (next search reads through the FK), no `set_payload` mutation needed.
- Qdrant collection bootstrap moves to `episodes/apps.ready()` (one-time at process startup) plus 409-tolerant `create_collection` — addresses the parallel-embed cold-start race flagged by external review.

### Added

- `RAGTIME_MUSICBRAINZ_DB_HOST/_PORT/_NAME/_USER/_PASSWORD` and `RAGTIME_MUSICBRAINZ_SCHEMA` env vars (defaults inherit from `RAGTIME_DB_*`, schema defaults to `musicbrainz`). `RAGTIME_EPISODE_CONCURRENCY` env var (default 4). Wired through `.env.sample` and the `manage.py configure` wizard (new MusicBrainz + Pipeline sections).
- `manage.py enrich_entities [--retry-failed] [--limit N]` to backfill any entity in PENDING (or, with `--retry-failed`, FAILED/NOT_FOUND) Wikidata status.
- `Entity.musicbrainz_id` (UUID), `Entity.wikidata_status` (PENDING/RESOLVED/NOT_FOUND/FAILED), `Entity.wikidata_attempts`, `Entity.wikidata_last_attempted_at`. `EntityType.musicbrainz_table`, `EntityType.musicbrainz_filter`. Migration `0020_*`.
- `psycopg_pool>=3.2,<4` dependency in `pyproject.toml`.
- 61 new tests (12 for `episodes/musicbrainz.py`, 13 for `episodes/enrichment.py`, 4 search-time hydration tests in `episodes/tests/test_embed.py`, plus updates across `test_resolve.py`/`test_signals.py`/`test_admin.py`/`test_chunk.py`/`test_download.py`/`test_extract.py`/`test_summarize.py`/`test_transcribe.py`/`core/tests/test_configure.py`). Full suite goes from 261 → 322 passing — [plan](doc/plans/2026-04-27-musicbrainz-resolution.md), [feature](doc/features/2026-04-27-musicbrainz-resolution.md), [planning session](doc/sessions/2026-04-27-musicbrainz-resolution-planning-session.md), [implementation session](doc/sessions/2026-04-27-musicbrainz-resolution-implementation-session.md)

## 2026-04-24

### Added

- Episodes right rail + audio player in the Scott chat UI. A new collapsible right `<aside>` (`frontend/src/episodesPanel.tsx`) lists all `status=READY` episodes fetched from a new `GET /episodes/api/episodes/` endpoint, with a toggle button in the chat-pane header and a default-collapsed state to preserve chat width. Clicking an episode plays it from 0:00 in a persistent "now playing" bar (`frontend/src/audioPlayerBar.tsx`) docked at the bottom of the chat pane — the bar only renders when a track is active, supports expand/minimize/close, and is backed by a single shared `HTMLAudioElement` owned by `AudioPlayerProvider` (`frontend/src/audioPlayer.tsx`). Each chunk row in the existing `SearchChunksDisplay` card is now clickable (and keyboard-activatable) and seeks the player to the chunk's `start_time`. To reach the frontend, Scott's `search_chunks` tool forwards `episode_id`, `episode_audio_url`, `episode_image_url` in its returned dict; `ChunkSearchResult` gains `episode_audio_url`; and Qdrant payloads now include `episode_audio_url` (computed at embed time as `episode.audio_url or episode.audio_file.url`). Existing corpora pick up the new payload key by selecting episodes in the Django admin changelist and running the "Reprocess" action from the "embedding" step. 11 new tests (8 for `/episodes/api/episodes/`, 3 for the `episode_audio_url` payload including the `audio_file` fallback); `formatTime()` extracted to `frontend/src/time.ts`. No new `RAGTIME_*` env vars — [plan](doc/plans/2026-04-24-episodes-rail-and-audio-player.md), [feature](doc/features/2026-04-24-episodes-rail-and-audio-player.md), [planning session](doc/sessions/2026-04-24-episodes-rail-and-audio-player-planning-session.md), [implementation session](doc/sessions/2026-04-24-episodes-rail-and-audio-player-implementation-session.md)

## 2026-04-21

### Changed

- Conversation history UX — replace localStorage-based thread adapter with `RemoteThreadListAdapter` backed by Django API endpoints. All persisted conversations are now discoverable in the sidebar across browser sessions, with rename, delete, and LLM-powered auto-title generation via a new `POST /chat/api/conversations/<id>/generate-title/` endpoint. Switch chat theme from dark to light with warm brown primary matching the RAGtime branding; add RAGtime SVG banner to sidebar. Serve Django static files under ASGI via `ASGIStaticFilesHandler` in DEBUG mode. Clarify Scott's system prompt to explicitly translate/paraphrase chunk content when it's in a different language than the user's question. Make `dbreset` only clear data and print explicit next steps instead of auto-running migrate. Add telemetry subsection to README — [plan](doc/plans/2026-04-21-conversation-history-ux.md), [feature](doc/features/2026-04-21-conversation-history-ux.md), [planning session](doc/sessions/2026-04-21-conversation-history-ux-planning-session.md), [implementation session](doc/sessions/2026-04-21-conversation-history-ux-implementation-session.md)

## 2026-04-20

### Added

- Scott — RAG chatbot. First working version of the strict-RAG jazz podcast chat agent. Adds a new `chat` Django app with `Conversation` / `Message` models and API endpoints (including `GET`/`POST /chat/api/conversations/<id>/history/` round-tripping assistant-ui's `ExportedMessageRepository`); a Pydantic AI `Agent` (`chat/agent.py`) with a `search_chunks` tool that retrieves from Qdrant and a strict-RAG system prompt forbidding general-knowledge fallbacks; `ChunkSearchResult` + `search_chunks()` in `episodes/vector_store.py` (embed query → `query_points` with optional episode filter and score threshold). The agent is exposed per-request via `AGUIAdapter.dispatch_request(...)` mounted as a tiny Starlette app inside Django's ASGI stack at `/chat/agent/` behind session-cookie auth middleware — each request gets a fresh `StateDeps(ScottState())` so the citation registry cannot leak across users. Frontend is a React island under `frontend/` built with Vite + `django-vite` + Tailwind 4 + assistant-ui + `@assistant-ui/react-ag-ui` (`useAgUiRuntime` connects directly to AG-UI — no CopilotKit runtime bridge, no Next.js). Conversation persistence is end-to-end: assistant-ui's `threadList` and `history` adapters are wired to the Django endpoints, so switching between threads or refreshing the page replays the full message tree from Postgres. Added `RAGTIME_SCOTT_PROVIDER`, `RAGTIME_SCOTT_MODEL`, `RAGTIME_SCOTT_API_KEY`, `RAGTIME_SCOTT_TOP_K`, `RAGTIME_SCOTT_SCORE_THRESHOLD`, `LOGIN_URL`, `LOGIN_REDIRECT_URL`, plus Django auth routes at `/accounts/login|logout/` (admin-provisioned users only). Test suite covers retrieval passthrough, agent refusal on empty retrieval, citation integrity (every `[N]` maps to `ScottState.retrieved_chunks`), cross-request `ScottState` isolation, auth gating via direct ASGI invocation, conversation lifecycle + history round-trip preserving parent-id chains + idempotent duplicate appends + owner scoping — [plan](doc/plans/2026-04-20-scott-rag-chatbot.md), [feature](doc/features/2026-04-20-scott-rag-chatbot.md), [planning session](doc/sessions/2026-04-20-scott-rag-chatbot-planning-session.md), [implementation session](doc/sessions/2026-04-20-scott-rag-chatbot-implementation-session.md)

## 2026-04-19

### Changed

- Replace Django Q2 task queue with DBOS Transact durable workflows — pipeline steps now run as a single `@DBOS.workflow()` with PostgreSQL-backed checkpointing instead of signal-driven `async_task()` dispatch. Eliminates the need for a separate `qcluster` worker process. Stepping stone for planned Pydantic AI agent-based architecture — [plan](doc/plans/2026-04-19-dbos-migration.md), [feature](doc/features/2026-04-19-dbos-migration.md), [planning session](doc/sessions/2026-04-19-dbos-migration-planning-session.md), [implementation session](doc/sessions/2026-04-19-dbos-migration-implementation-session.md)

### Added

- Embed step (pipeline step 9) — generate multilingual OpenAI `text-embedding-3-small` embeddings for every chunk and upsert them into a [Qdrant](https://qdrant.tech/) collection with chunk + episode + entity metadata. Adds `episodes/embedder.py`, `episodes/vector_store.py` (`QdrantVectorStore` with fail-fast dim check and episode-scoped deletes), `OpenAIEmbeddingProvider`, and `get_embedding_provider()` factory. `docker-compose.yml` now runs a Qdrant service alongside Postgres; `manage.py dbreset` also drops the Qdrant collection; a `post_delete` signal on `Episode` cleans Qdrant when an episode is deleted from the admin — [plan](doc/plans/2026-04-19-embed-step.md), [feature](doc/features/2026-04-19-embed-step.md), [planning session](doc/sessions/2026-04-19-embed-step-planning-session.md), [implementation session](doc/sessions/2026-04-19-embed-step-implementation-session.md)

### Changed

- Remove LangGraph from the roadmap — delete the "LangGraph pipeline" bullet from the "What's coming" section of `README.md`. LangGraph is no longer planned: Pydantic AI already covers the project's agentic needs (used in the recovery layer), LangGraph's observability and Studio tooling lean on LangSmith, and LangSmith is a hosted-only service that conflicts with RAGtime's preference for locally runnable telemetry collectors (console, Jaeger, self-hosted Langfuse via OpenTelemetry) — [plan](doc/plans/2026-04-19-remove-langgraph-roadmap.md), [feature](doc/features/2026-04-19-remove-langgraph-roadmap.md), [planning session](doc/sessions/2026-04-19-remove-langgraph-roadmap-planning-session.md), [implementation session](doc/sessions/2026-04-19-remove-langgraph-roadmap-implementation-session.md)

### Removed

- ChromaDB placeholder env vars (`RAGTIME_VECTOR_STORE`, `RAGTIME_CHROMA_HOST`, `RAGTIME_CHROMA_PORT`, `RAGTIME_CHROMA_COLLECTION`). Replaced by `RAGTIME_QDRANT_*` with the Embed step implementation above.

### Fixed

- `docker-compose.yml` duplicated PostgreSQL credentials — replace hard-coded `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, and the published port with Compose variable substitution (`${RAGTIME_DB_NAME:-ragtime}`, etc.), so `.env` / `manage.py configure` becomes the single source of truth. Healthcheck `pg_isready -U` also follows the substituted user. Apply the same treatment to Qdrant's published HTTP port via `${RAGTIME_QDRANT_PORT:-6333}`. Rename the `db` service to `postgres` to match the image name and the existing CI workflow service name. Restructure `README.md` "Getting Started" into Installation / Configuration / Running the services so configure runs before `docker compose up`, making the causal chain visible (configure → docker compose reads `.env` → start services). Literal defaults preserve zero-config `docker compose up` behaviour; no new env vars introduced — [plan](doc/plans/2026-04-19-fix-docker-compose-env-vars.md), [feature](doc/features/2026-04-19-fix-docker-compose-env-vars.md), [planning session](doc/sessions/2026-04-19-fix-docker-compose-env-vars-planning-session.md), [implementation session](doc/sessions/2026-04-19-fix-docker-compose-env-vars-implementation-session.md)

## 2026-04-15

### Changed

- Replace Langfuse-specific observability with OpenTelemetry telemetry — `episodes/observability.py` replaced by `episodes/telemetry.py` with OTel as a core dependency. Three optional collectors: console (stdout), Jaeger (via OTLP), and Langfuse (via OTel SpanProcessor). Multiple collectors can run simultaneously. `RAGTIME_OTEL_COLLECTORS` env var replaces `RAGTIME_LANGFUSE_ENABLED`. OpenAI calls auto-instrumented via `opentelemetry-instrumentation-openai` instead of Langfuse monkey-patched client. Jaeger supported via standalone `docker run` — [plan](doc/plans/2026-04-15-opentelemetry-telemetry.md), [feature](doc/features/2026-04-15-opentelemetry-telemetry.md), [planning session](doc/sessions/2026-04-15-opentelemetry-telemetry-planning-session.md), [implementation session](doc/sessions/2026-04-15-opentelemetry-telemetry-implementation-session.md)

## 2026-03-23

### Fixed

- Scraper save overwrites recovery status — when LLM extraction returns incomplete metadata, `fail_step()` triggers recovery synchronously and the agent sets `status=TRANSCRIBING`, but the scraper's subsequent `episode.save()` overwrites it back to `FAILED` from a stale local object. Fix by saving before `fail_step()`, matching the pattern used by every other pipeline step. Also fix resolver crash (`value too long for type character varying(20)`) by sanitizing LLM-returned `wikidata_id` values to extract bare Q-IDs — [plan](doc/plans/2026-03-23-fix-scraper-recovery-status-overwrite.md), [feature](doc/features/2026-03-23-fix-scraper-recovery-status-overwrite.md), [planning session](doc/sessions/2026-03-23-fix-scraper-recovery-status-overwrite-planning-session.md), [implementation session](doc/sessions/2026-03-23-fix-scraper-recovery-status-overwrite-implementation-session.md)

- Transcription step missing from Langfuse traces — add `@observe_provider` and input/output logging to `OpenAITranscriptionProvider.transcribe()` so the request parameters and Whisper response are visible in Langfuse. Extend `set_observation_input` to support dict-style keyword arguments for non-chat providers — [plan](doc/plans/2026-03-23-fix-transcribe-langfuse-observability.md), [feature](doc/features/2026-03-23-fix-transcribe-langfuse-observability.md), [planning session](doc/sessions/2026-03-23-fix-transcribe-langfuse-observability-planning-session.md), [implementation session](doc/sessions/2026-03-23-fix-transcribe-langfuse-observability-implementation-session.md)

- Recovery agent downloaded file lost before pipeline resumes — fix `TemporaryDirectory` race condition where the temp dir was cleaned up before `resume_pipeline()` could access the downloaded file, and make scraping recovery skip the download step when the agent already downloaded the file using browser cookies (avoids redundant `wget` download that fails without session cookies) — [plan](doc/plans/2026-03-23-fix-recovery-downloaded-file-lost.md), [feature](doc/features/2026-03-23-fix-recovery-downloaded-file-lost.md), [planning session](doc/sessions/2026-03-23-fix-recovery-downloaded-file-lost-planning-session.md), [implementation session](doc/sessions/2026-03-23-fix-recovery-downloaded-file-lost-implementation-session.md)

### Added

- Recovery agent language awareness — pass episode language to the recovery agent, add `translate_text` tool (backed by dedicated `RAGTIME_TRANSLATION_*` provider) so the agent translates UI labels before clicking on non-English pages. Add visual analysis fallback: `analyze_screenshot` returns screenshots for LLM visual interpretation, `click_at_coordinates` clicks visually identified elements, `intercept_audio_requests` captures streaming audio URLs via network interception — [plan](doc/plans/2026-03-23-recovery-agent-language-awareness.md), [feature](doc/features/2026-03-23-recovery-agent-language-awareness.md), [planning session](doc/sessions/2026-03-23-recovery-agent-language-awareness-planning-session.md), [implementation session](doc/sessions/2026-03-23-recovery-agent-language-awareness-implementation-session.md)

### Changed

- Unified recovery agent system prompt — merge separate scraping/downloading prompts into one, add cookie-first download strategy, mandatory screenshots after every action, and conditional language section with translation checklist for non-English episodes
- Switch `download_file` from Playwright `expect_download()` to `page.context.request.get()` for reliable downloads using the browser's cookies and session
- Detach recovery agent from parent Langfuse trace context so it gets its own independent root trace
- Increase recovery agent request limit from 15 to 30 to accommodate new tools

- Switch from SQLite to PostgreSQL with Docker Compose — resolve concurrent write locking errors from parallel Django Q2 workers. Add `docker-compose.yml` with PostgreSQL 17, `manage.py dbreset` command, `RAGTIME_DB_*` configuration, CI workflow with PostgreSQL service container, and custom test runner for clean database teardown. Add timestamps to Langfuse session IDs for uniqueness across database resets — [plan](doc/plans/2026-03-23-postgresql-docker-compose.md), [feature](doc/features/2026-03-23-postgresql-docker-compose.md), [planning session](doc/sessions/2026-03-23-postgresql-docker-compose-planning-session.md), [implementation session](doc/sessions/2026-03-23-postgresql-docker-compose-implementation-session.md)

## 2026-03-21

### Added

- Entity mention timestamps — resolve word-level timestamps from Whisper transcripts during entity extraction so users can jump directly to where an entity is mentioned in a podcast episode. Adds `start_time` to EntityMention model, sliding window word matching with partial fallback, and 19 new tests — [plan](doc/plans/2026-03-21-entity-mention-timestamps.md), [feature](doc/features/2026-03-21-entity-mention-timestamps.md), [planning session](doc/sessions/2026-03-21-entity-mention-timestamps-planning-session.md), [implementation session](doc/sessions/2026-03-21-entity-mention-timestamps-implementation-session.md)

- Wikidata cache persistence — switch default cache backend from in-memory (`locmem`) to file-based (`filebased`), add token bucket rate limiter (5 req/s, burst 10) for API requests, document cache clearing — [plan](doc/plans/2026-03-21-wikidata-cache-persistence.md), [feature](doc/features/2026-03-21-wikidata-cache-persistence.md), [planning session](doc/sessions/2026-03-21-wikidata-cache-persistence-planning-session.md), [implementation session](doc/sessions/2026-03-21-wikidata-cache-persistence-implementation-session.md)

### Changed

- Session transcript compliance — regenerate all 40 session transcripts with verbatim content from JSONL logs, fix metadata ordering (Date before Session ID), rename 15 files to `-planning-session.md`/`-implementation-session.md` convention, split 5 combined transcripts into separate planning+implementation files, update CHANGELOG references, tighten AGENTS.md format rules — [plan](doc/plans/2026-03-21-session-transcript-compliance.md), [feature](doc/features/2026-03-21-session-transcript-compliance.md), [planning session](doc/sessions/2026-03-21-session-transcript-compliance-planning-session.md), [implementation session](doc/sessions/2026-03-21-session-transcript-compliance-implementation-session.md)

## 2026-03-20

### Changed

- Split README into concise root overview and detailed `doc/README.md` with full pipeline step descriptions, How Scott Works, and Langfuse observability sections. Move `ragtime.svg` and `ragtime.png` into `doc/`. Replace verbose pipeline steps with a compact summary table in root README — [plan](doc/plans/2026-03-20-readme-split.md), [feature](doc/features/2026-03-20-readme-split.md), [planning session](doc/sessions/2026-03-20-readme-split-planning-session.md), [implementation session](doc/sessions/2026-03-20-readme-split-implementation-session.md)

## 2026-03-19

### Added

- Agent Recovery Strategy — Pydantic AI agent with Playwright browser automation recovers from scraping and downloading failures by navigating podcast pages, finding audio URLs, and downloading files through a headless browser. Includes Django admin "Retry with recovery agent" action, Langfuse tracing with screenshot attachments, and 3 new configuration variables — [plan](doc/plans/2026-03-19-agent-recovery-strategy.md), [feature](doc/features/2026-03-19-agent-recovery-strategy.md), [planning session](doc/sessions/2026-03-19-agent-recovery-strategy-planning-session.md), [implementation session](doc/sessions/2026-03-19-agent-recovery-strategy-implementation-session.md)

## 2026-03-18

### Added

- Decoupled Recovery Architecture — structured pipeline events (StepCompletedEvent/StepFailureEvent), pluggable recovery layer with strategy chain (agent → human), PipelineEvent and RecoveryAttempt models for audit trail, admin integration with colour-coded events and "Needs Human Action" filter — [plan](doc/plans/2026-03-18-decoupled-recovery-architecture.md), [feature](doc/features/2026-03-18-decoupled-recovery-architecture.md), [planning session](doc/sessions/2026-03-18-decoupled-recovery-architecture-planning-session.md), [implementation session](doc/sessions/2026-03-18-decoupled-recovery-architecture-implementation-session.md)

### Removed

- `NEEDS_REVIEW` episode status — replaced by `FAILED` status with recovery chain escalation to human. Incomplete metadata after scraping now triggers the recovery layer instead of requiring manual status management.

## 2026-03-17

### Changed

- Clarify Extract and Resolve README sections — rewrite pipeline steps 7 and 8 with NER/NEL labels, concrete example tables, and two-phase design rationale — [plan](doc/plans/2026-03-17-clarify-extract-resolve-readme.md), [feature](doc/features/2026-03-17-clarify-extract-resolve-readme.md), [planning session](doc/sessions/2026-03-17-clarify-extract-resolve-readme-planning-session.md), [implementation session](doc/sessions/2026-03-17-clarify-extract-resolve-readme-implementation-session.md)

## 2026-03-16

### Added

- Optional Langfuse LLM Observability — trace all OpenAI API calls across the 5 LLM pipeline steps (scrape, transcribe, summarize, extract, resolve), grouped by ProcessingRun session. Zero overhead when disabled. Install with `uv sync --extra observability` — [plan](doc/plans/2026-03-16-langfuse-observability.md), [feature](doc/features/2026-03-16-langfuse-observability.md), [planning session](doc/sessions/2026-03-16-langfuse-observability-planning-session.md), [implementation session](doc/sessions/2026-03-16-langfuse-observability-implementation-session.md)

### Changed

- Rename Entity Type Keys to Match Wikidata Labels — align 8 entity type keys, names, and descriptions with official Wikidata labels (e.g., artist -> musician, band -> musical_group), fix incorrect Q-ID for recording_session (was a galaxy, now Q98216532) — [plan](doc/plans/2026-03-16-wikidata-entity-type-renames.md), [feature](doc/features/2026-03-16-wikidata-entity-type-renames.md), [planning session](doc/sessions/2026-03-16-wikidata-entity-type-renames-planning-session.md), [implementation session](doc/sessions/2026-03-16-wikidata-entity-type-renames-implementation-session.md)

## 2026-03-15

### Added

- Wikidata Integration for Entity Resolution — add `wikidata_id` fields to EntityType and Entity models, Wikidata API client with database caching, candidate lookup during resolution (LLM confirms best Q-ID match), `lookup_entity` management command for CLI search, rename pipeline sections to "Extract entities" / "Resolve entities" — [plan](doc/plans/2026-03-15-wikidata-integration.md), [feature](doc/features/2026-03-15-wikidata-integration.md), [planning session](doc/sessions/2026-03-15-wikidata-integration-planning-session.md), [implementation session](doc/sessions/2026-03-15-wikidata-integration-implementation-session.md)

- Adaptive Audio Resize Tiers — select the gentlest ffmpeg settings that fit under the Whisper API size limit based on episode duration, instead of always using the most aggressive compression — [plan](doc/plans/2026-03-15-adaptive-audio-resize-tiers.md), [feature](doc/features/2026-03-15-adaptive-audio-resize-tiers.md), [planning session](doc/sessions/2026-03-15-adaptive-audio-resize-tiers-planning-session.md), [implementation session](doc/sessions/2026-03-15-adaptive-audio-resize-tiers-implementation-session.md)

- Chunk-level Entity Extraction — extract entities per chunk instead of per episode, linking each entity mention to the specific chunk (and timestamp) where it appeared. Resolution aggregates unique names across chunks before resolving — [plan](doc/plans/2026-03-15-chunk-level-entity-extraction.md), [feature](doc/features/2026-03-15-chunk-level-entity-extraction.md), [planning session](doc/sessions/2026-03-15-chunk-level-entity-extraction-planning-session.md), [implementation session](doc/sessions/2026-03-15-chunk-level-entity-extraction-implementation-session.md)

### Changed

- Merge Resize into Transcribe — absorb ffmpeg downsampling into the transcribe step, reducing the pipeline from 11 to 10 steps. Resize was a transcription provider implementation detail, not a meaningful domain event — [plan](doc/plans/2026-03-15-merge-resize-into-transcribe.md), [feature](doc/features/2026-03-15-merge-resize-into-transcribe.md), [planning session](doc/sessions/2026-03-15-merge-resize-into-transcribe-planning-session.md), [implementation session](doc/sessions/2026-03-15-merge-resize-into-transcribe-implementation-session.md)
- Restructure README Processing Pipeline from table to numbered emoji list, fold Extracted Entities section into Step 9 — [PR](https://github.com/rafacm/ragtime/pull/43)
- Convert README pipeline section from numbered list to `###` subsections, fix 7 step descriptions to match implementation — [plan](doc/plans/2026-03-15-readme-pipeline-subsections.md), [feature](doc/features/2026-03-15-readme-pipeline-subsections.md), [planning session](doc/sessions/2026-03-15-readme-pipeline-subsections-planning-session.md), [implementation session](doc/sessions/2026-03-15-readme-pipeline-subsections-implementation-session.md)

## 2026-03-14

### Added

- Step 8: Chunk Transcript — split Whisper transcript into overlapping chunks by segment boundaries, with own `chunking` status and reordered pipeline placement before extraction — [plan](doc/plans/2026-03-14-step-08-chunk.md), [feature](doc/features/2026-03-14-step-08-chunk.md)
- Processing Status Tracking — per-step tracking with ProcessingRun/ProcessingStep models, retry from failure point, unified reprocess action with intermediate page — [plan](doc/plans/2026-03-14-processing-status-tracking.md), [feature](doc/features/2026-03-14-processing-status-tracking.md), [planning session](doc/sessions/2026-03-14-processing-status-tracking-planning-session.md), [implementation session](doc/sessions/2026-03-14-processing-status-tracking-implementation-session.md)
- Episode Duration — extract MP3 duration via mutagen after download, display as HH:MM:SS in admin, reorder list columns to lead with Title — [plan](doc/plans/2026-03-14-episode-duration.md), [feature](doc/features/2026-03-14-episode-duration.md), [planning session](doc/sessions/2026-03-14-episode-duration-planning-session.md), [implementation session](doc/sessions/2026-03-14-episode-duration-implementation-session.md)

### Changed

- Move Entity Types from YAML to Database — DB-backed EntityType model with Django admin UI, PROTECT deletion, is_active flag, comma-separated examples input, `load_entity_types` management command — [plan](doc/plans/2026-03-14-entity-types-to-db.md), [feature](doc/features/2026-03-14-entity-types-to-db.md), [planning session](doc/sessions/2026-03-14-entity-types-to-db-planning-session.md), [implementation session](doc/sessions/2026-03-14-entity-types-to-db-implementation-session.md)
- Replace httpx MP3 download with wget — avoids User-Agent blocking by podcast websites, adds wget to prerequisites — [PR](https://github.com/rafacm/ragtime/pull/28)

### Fixed

- Move "Name" to first column in Entity admin list — makes Name the clickable link to the detail page — [PR](https://github.com/rafacm/ragtime/pull/31)
- Download task never queued after LLM extraction — scraper's bare `save()` missed `update_fields`, so the post_save signal never dispatched the download task — [PR](https://github.com/rafacm/ragtime/pull/27)

## 2026-03-13

### Added

- Step 9: Resolve Entities — LLM-based entity resolution against existing DB records with fuzzy matching, canonical naming, and cross-language support — [plan](doc/plans/2026-03-13-step-09-resolve-entities.md), [feature](doc/features/2026-03-13-step-09-resolve-entities.md), [planning session](doc/sessions/2026-03-13-step-09-resolve-entities-planning-session.md), [implementation session](doc/sessions/2026-03-13-step-09-resolve-entities-implementation-session.md)
- `manage.py configure` — Interactive setup wizard for RAGTIME_* environment variables with shared credentials, secret masking, and `--show` flag — [plan](doc/plans/2026-03-13-manage-py-configure.md), [feature](doc/features/2026-03-13-manage-py-configure.md), [planning session](doc/sessions/2026-03-13-manage-py-configure-planning-session.md), [implementation session](doc/sessions/2026-03-13-manage-py-configure-implementation-session.md)
- Step 8: Extract Entities — LLM-based entity extraction (artists, albums, venues, etc.) with independently configurable provider — [plan](doc/plans/2026-03-13-step-08-extract-entities.md), [feature](doc/features/2026-03-13-step-08-extract-entities.md), [implementation session](doc/sessions/2026-03-13-step-08-extract-entities-implementation-session.md)

### Changed

- Rename RAGTIME_LLM_* → RAGTIME_SCRAPING_* — align scraping provider naming with RAGTIME_\<PURPOSE\>_* convention — [plan](doc/plans/2026-03-13-refactor-rename-scraping-provider.md), [feature](doc/features/2026-03-13-refactor-rename-scraping-provider.md), [planning session](doc/sessions/2026-03-13-rename-scraping-provider-planning-session.md), [implementation session](doc/sessions/2026-03-13-rename-scraping-provider-implementation-session.md)
- Multi-session transcript format — session IDs, reasoning steps, multi-session coverage — [feature](doc/features/2026-03-13-session-transcript-format.md), [implementation session](doc/sessions/2026-03-13-session-transcript-format-implementation-session.md)
- Split episode tests into a test package — 9 focused modules under `episodes/tests/`, one per component — [implementation session](doc/sessions/2026-03-13-refactor-episode-tests-implementation-session.md)

## 2026-03-11

### Added

- Step 7: Summarize — LLM-generated episode summaries with independently configurable summarization provider — [plan](doc/plans/2026-03-11-step-07-summarize.md), [feature](doc/features/2026-03-11-step-07-summarize.md), [implementation session](doc/sessions/2026-03-11-step-07-summarize-implementation-session.md)
- Step 6: Transcribe — Whisper API transcription with segment and word timestamps, pluggable provider abstraction — [plan](doc/plans/2026-03-11-step-06-transcribe.md), [feature](doc/features/2026-03-11-step-06-transcribe.md), [implementation session](doc/sessions/2026-03-11-step-06-transcribe-implementation-session.md)

### Fixed

- Summarization respects episode language — summaries generated in the episode's language instead of defaulting to English — [feature](doc/features/2026-03-11-fix-summarization-language.md), [implementation session](doc/sessions/2026-03-11-fix-summarization-language-implementation-session.md)

## 2026-03-10

### Added

- CI: GitHub Actions — Automated test suite on PRs and pushes to main, README badges for build status, Python, Django, license — [feature](doc/features/2026-03-10-ci-github-actions.md), [implementation session](doc/sessions/2026-03-10-ci-github-actions-implementation-session.md)

## 2026-03-09

### Added

- Steps 4 & 5: Download & Resize — Audio download with streaming, ffmpeg downsampling for Whisper API limit, error tracking — [plan](doc/plans/2026-03-09-step-04-05-download-resize.md), [feature](doc/features/2026-03-09-step-04-05-download-resize.md), [implementation session](doc/sessions/2026-03-09-step-04-05-download-resize-implementation-session.md)
- Step 3: Scrape — LLM-based metadata extraction with Django Q2 async tasks, provider abstraction, and needs_review workflow — [plan](doc/plans/2026-03-09-step-03-scrape.md), [feature](doc/features/2026-03-09-step-03-scrape.md), [implementation session](doc/sessions/2026-03-09-step-03-scrape-implementation-session.md)
- Step 2: Dedup — Duplicate episode detection via unique URL constraint at database level — [plan](doc/plans/2026-03-09-step-02-dedup.md), [feature](doc/features/2026-03-09-step-02-dedup.md), [implementation session](doc/sessions/2026-03-09-step-02-dedup-implementation-session.md)
- Step 1: Submit Episode — Django project bootstrap, Episode model with status tracking, admin interface — [plan](doc/plans/2026-03-09-step-01-submit-episode.md), [feature](doc/features/2026-03-09-step-01-submit-episode.md), [implementation session](doc/sessions/2026-03-09-step-01-submit-episode-implementation-session.md)
