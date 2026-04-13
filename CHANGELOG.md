# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## 2026-04-13

### Changed

- Migrate observability from Langfuse to OpenTelemetry — replace Langfuse-specific decorators (`@observe_step`, `@observe_provider`) and client wrapping with OTel SDK (`@trace_step`, `@trace_provider`, span events). Traces can now be exported to any OTLP-compatible backend (Langfuse, Sentry, Jaeger). Replace `RAGTIME_LANGFUSE_*` env vars with `RAGTIME_OTEL_*` — [plan](doc/plans/2026-04-13-otel-langgraph-migration.md), [feature](doc/features/2026-04-13-otel-langgraph-migration.md), [planning session](doc/sessions/2026-04-13-otel-langgraph-migration-planning-session.md), [implementation session](doc/sessions/2026-04-13-otel-langgraph-migration-implementation-session.md)

- Replace Django Q2 signal-based pipeline dispatch with LangGraph state graph — the ingestion pipeline is now a compiled `StateGraph` with conditional edges for step skipping (when data already exists) and recovery routing. An entry router enables resume-from-failure. Remove `django-q2` dependency, `Q_CLUSTER` config, and `queue_next_step` signal handler — [plan](doc/plans/2026-04-13-otel-langgraph-migration.md), [feature](doc/features/2026-04-13-otel-langgraph-migration.md), [planning session](doc/sessions/2026-04-13-otel-langgraph-migration-planning-session.md), [implementation session](doc/sessions/2026-04-13-otel-langgraph-migration-implementation-session.md)

### Added

- LangGraph Studio support — `langgraph.json` and `episodes/graph/server.py` enable local graph visualization and execution inspection via LangGraph Studio desktop app (`langgraph dev`)

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
