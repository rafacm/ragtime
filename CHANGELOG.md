# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- Processing Status Tracking — per-step tracking with ProcessingRun/ProcessingStep models, retry from failure point, unified reprocess action with intermediate page (2026-03-14) — [plan](doc/plans/processing-status-tracking.md), [feature](doc/features/processing-status-tracking.md), [session](doc/sessions/2026-03-14-processing-status-tracking.md)
- Step 9: Resolve Entities — LLM-based entity resolution against existing DB records with fuzzy matching, canonical naming, and cross-language support (2026-03-13) — [plan](doc/plans/step-09-resolve-entities.md), [feature](doc/features/step-09-resolve-entities.md), [session](doc/sessions/2026-03-13-step-09-resolve-entities.md)
- `manage.py configure` — Interactive setup wizard for RAGTIME_* environment variables with shared credentials, secret masking, and `--show` flag (2026-03-13) — [plan](doc/plans/manage-py-configure.md), [feature](doc/features/manage-py-configure.md), [session](doc/sessions/2026-03-13-manage-py-configure.md)
- Step 8: Extract Entities — LLM-based entity extraction (artists, albums, venues, etc.) with independently configurable provider (2026-03-13) — [plan](doc/plans/step-08-extract-entities.md), [feature](doc/features/step-08-extract-entities.md), [session](doc/sessions/2026-03-13-step-08-extract-entities.md)
- Step 7: Summarize — LLM-generated episode summaries with independently configurable summarization provider (2026-03-11) — [plan](doc/plans/step-07-summarize.md), [feature](doc/features/step-07-summarize.md), [session](doc/sessions/2026-03-11-step-07-summarize.md)
- Step 6: Transcribe — Whisper API transcription with segment and word timestamps, pluggable provider abstraction (2026-03-11) — [plan](doc/plans/step-06-transcribe.md), [feature](doc/features/step-06-transcribe.md), [session](doc/sessions/2026-03-11-step-06-transcribe.md)
- CI: GitHub Actions — Automated test suite on PRs and pushes to main, README badges for build status, Python, Django, license (2026-03-10) — [feature](doc/features/ci-github-actions.md), [session](doc/sessions/2026-03-10-ci-github-actions.md)
- Steps 4 & 5: Download & Resize — Audio download with streaming, ffmpeg downsampling for Whisper API limit, error tracking (2026-03-09) — [plan](doc/plans/step-04-05-download-resize.md), [feature](doc/features/step-04-05-download-resize.md), [session](doc/sessions/2026-03-09-step-04-05-download-resize.md)
- Step 3: Scrape — LLM-based metadata extraction with Django Q2 async tasks, provider abstraction, and needs_review workflow (2026-03-09) — [plan](doc/plans/step-03-scrape.md), [feature](doc/features/step-03-scrape.md), [session](doc/sessions/2026-03-09-step-03-scrape.md)
- Step 2: Dedup — Duplicate episode detection via unique URL constraint at database level (2026-03-09) — [plan](doc/plans/step-02-dedup.md), [feature](doc/features/step-02-dedup.md), [session](doc/sessions/2026-03-09-step-02-dedup.md)
- Step 1: Submit Episode — Django project bootstrap, Episode model with status tracking, admin interface (2026-03-09) — [plan](doc/plans/step-01-submit-episode.md), [feature](doc/features/step-01-submit-episode.md), [session](doc/sessions/2026-03-09-step-01-submit-episode.md)

### Changed

- Move Entity Types from YAML to Database — DB-backed EntityType model with Django admin UI, PROTECT deletion, is_active flag, comma-separated examples input, `load_entity_types` management command (2026-03-14) — [plan](doc/plans/entity-types-to-db.md), [feature](doc/features/entity-types-to-db.md), [planning session](doc/sessions/2026-03-14-entity-types-to-db-planning-session.md), [implementation session](doc/sessions/2026-03-14-entity-types-to-db-implementation-session.md)
- Replace httpx MP3 download with wget — avoids User-Agent blocking by podcast websites, adds wget to prerequisites (2026-03-14) — [PR](https://github.com/rafacm/ragtime/pull/28)
- Rename RAGTIME_LLM_* → RAGTIME_SCRAPING_* — align scraping provider naming with RAGTIME_\<PURPOSE\>_* convention (2026-03-13) — [plan](doc/plans/refactor-rename-scraping-provider.md), [feature](doc/features/refactor-rename-scraping-provider.md), [session](doc/sessions/2026-03-13-rename-scraping-provider.md)
- Multi-session transcript format — session IDs, reasoning steps, multi-session coverage (2026-03-13) — [feature](doc/features/session-transcript-format.md), [session](doc/sessions/2026-03-13-session-transcript-format.md)
- Split episode tests into a test package — 9 focused modules under `episodes/tests/`, one per component (2026-03-13) — [session](doc/sessions/2026-03-13-refactor-episode-tests.md)

### Fixed

- Move "Name" to first column in Entity admin list — makes Name the clickable link to the detail page (2026-03-14) — [PR](https://github.com/rafacm/ragtime/pull/31)
- Download task never queued after LLM extraction — scraper's bare `save()` missed `update_fields`, so the post_save signal never dispatched the download task (2026-03-14) — [PR](https://github.com/rafacm/ragtime/pull/27)
- Summarization respects episode language — summaries generated in the episode's language instead of defaulting to English (2026-03-11) — [feature](doc/features/fix-summarization-language.md), [session](doc/sessions/2026-03-11-fix-summarization-language.md)
