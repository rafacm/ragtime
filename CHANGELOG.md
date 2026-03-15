# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## 2026-03-15

### Added

- Adaptive Audio Resize Tiers — select the gentlest ffmpeg settings that fit under the Whisper API size limit based on episode duration, instead of always using the most aggressive compression — [plan](doc/plans/adaptive-audio-resize-tiers.md), [feature](doc/features/adaptive-audio-resize-tiers.md), [planning session](doc/sessions/2026-03-15-adaptive-audio-resize-tiers-planning-session.md), [implementation session](doc/sessions/2026-03-15-adaptive-audio-resize-tiers-implementation-session.md)

### Changed

- Merge Resize into Transcribe — absorb ffmpeg downsampling into the transcribe step, reducing the pipeline from 11 to 10 steps. Resize was a transcription provider implementation detail, not a meaningful domain event — [plan](doc/plans/merge-resize-into-transcribe.md), [feature](doc/features/merge-resize-into-transcribe.md), [planning session](doc/sessions/2026-03-15-merge-resize-into-transcribe-planning-session.md), [implementation session](doc/sessions/2026-03-15-merge-resize-into-transcribe-implementation-session.md)
- Restructure README Processing Pipeline from table to numbered emoji list, fold Extracted Entities section into Step 9 — [PR](https://github.com/rafacm/ragtime/pull/43)
- Convert README pipeline section from numbered list to `###` subsections, fix 7 step descriptions to match implementation — [plan](doc/plans/readme-pipeline-subsections.md), [feature](doc/features/readme-pipeline-subsections.md), [planning session](doc/sessions/2026-03-15-readme-pipeline-subsections-planning-session.md), [implementation session](doc/sessions/2026-03-15-readme-pipeline-subsections-implementation-session.md)

## 2026-03-14

### Added

- Step 8: Chunk Transcript — split Whisper transcript into overlapping chunks by segment boundaries, with own `chunking` status and reordered pipeline placement before extraction — [plan](doc/plans/step-08-chunk.md), [feature](doc/features/step-08-chunk.md)
- Processing Status Tracking — per-step tracking with ProcessingRun/ProcessingStep models, retry from failure point, unified reprocess action with intermediate page — [plan](doc/plans/processing-status-tracking.md), [feature](doc/features/processing-status-tracking.md), [session](doc/sessions/2026-03-14-processing-status-tracking.md)
- Episode Duration — extract MP3 duration via mutagen after download, display as HH:MM:SS in admin, reorder list columns to lead with Title — [plan](doc/plans/episode-duration.md), [feature](doc/features/episode-duration.md), [planning session](doc/sessions/2026-03-14-episode-duration-planning-session.md), [implementation session](doc/sessions/2026-03-14-episode-duration-implementation-session.md)

### Changed

- Move Entity Types from YAML to Database — DB-backed EntityType model with Django admin UI, PROTECT deletion, is_active flag, comma-separated examples input, `load_entity_types` management command — [plan](doc/plans/entity-types-to-db.md), [feature](doc/features/entity-types-to-db.md), [planning session](doc/sessions/2026-03-14-entity-types-to-db-planning-session.md), [implementation session](doc/sessions/2026-03-14-entity-types-to-db-implementation-session.md)
- Replace httpx MP3 download with wget — avoids User-Agent blocking by podcast websites, adds wget to prerequisites — [PR](https://github.com/rafacm/ragtime/pull/28)

### Fixed

- Move "Name" to first column in Entity admin list — makes Name the clickable link to the detail page — [PR](https://github.com/rafacm/ragtime/pull/31)
- Download task never queued after LLM extraction — scraper's bare `save()` missed `update_fields`, so the post_save signal never dispatched the download task — [PR](https://github.com/rafacm/ragtime/pull/27)

## 2026-03-13

### Added

- Step 9: Resolve Entities — LLM-based entity resolution against existing DB records with fuzzy matching, canonical naming, and cross-language support — [plan](doc/plans/step-09-resolve-entities.md), [feature](doc/features/step-09-resolve-entities.md), [session](doc/sessions/2026-03-13-step-09-resolve-entities.md)
- `manage.py configure` — Interactive setup wizard for RAGTIME_* environment variables with shared credentials, secret masking, and `--show` flag — [plan](doc/plans/manage-py-configure.md), [feature](doc/features/manage-py-configure.md), [session](doc/sessions/2026-03-13-manage-py-configure.md)
- Step 8: Extract Entities — LLM-based entity extraction (artists, albums, venues, etc.) with independently configurable provider — [plan](doc/plans/step-08-extract-entities.md), [feature](doc/features/step-08-extract-entities.md), [session](doc/sessions/2026-03-13-step-08-extract-entities.md)

### Changed

- Rename RAGTIME_LLM_* → RAGTIME_SCRAPING_* — align scraping provider naming with RAGTIME_\<PURPOSE\>_* convention — [plan](doc/plans/refactor-rename-scraping-provider.md), [feature](doc/features/refactor-rename-scraping-provider.md), [session](doc/sessions/2026-03-13-rename-scraping-provider.md)
- Multi-session transcript format — session IDs, reasoning steps, multi-session coverage — [feature](doc/features/session-transcript-format.md), [session](doc/sessions/2026-03-13-session-transcript-format.md)
- Split episode tests into a test package — 9 focused modules under `episodes/tests/`, one per component — [session](doc/sessions/2026-03-13-refactor-episode-tests.md)

## 2026-03-11

### Added

- Step 7: Summarize — LLM-generated episode summaries with independently configurable summarization provider — [plan](doc/plans/step-07-summarize.md), [feature](doc/features/step-07-summarize.md), [session](doc/sessions/2026-03-11-step-07-summarize.md)
- Step 6: Transcribe — Whisper API transcription with segment and word timestamps, pluggable provider abstraction — [plan](doc/plans/step-06-transcribe.md), [feature](doc/features/step-06-transcribe.md), [session](doc/sessions/2026-03-11-step-06-transcribe.md)

### Fixed

- Summarization respects episode language — summaries generated in the episode's language instead of defaulting to English — [feature](doc/features/fix-summarization-language.md), [session](doc/sessions/2026-03-11-fix-summarization-language.md)

## 2026-03-10

### Added

- CI: GitHub Actions — Automated test suite on PRs and pushes to main, README badges for build status, Python, Django, license — [feature](doc/features/ci-github-actions.md), [session](doc/sessions/2026-03-10-ci-github-actions.md)

## 2026-03-09

### Added

- Steps 4 & 5: Download & Resize — Audio download with streaming, ffmpeg downsampling for Whisper API limit, error tracking — [plan](doc/plans/step-04-05-download-resize.md), [feature](doc/features/step-04-05-download-resize.md), [session](doc/sessions/2026-03-09-step-04-05-download-resize.md)
- Step 3: Scrape — LLM-based metadata extraction with Django Q2 async tasks, provider abstraction, and needs_review workflow — [plan](doc/plans/step-03-scrape.md), [feature](doc/features/step-03-scrape.md), [session](doc/sessions/2026-03-09-step-03-scrape.md)
- Step 2: Dedup — Duplicate episode detection via unique URL constraint at database level — [plan](doc/plans/step-02-dedup.md), [feature](doc/features/step-02-dedup.md), [session](doc/sessions/2026-03-09-step-02-dedup.md)
- Step 1: Submit Episode — Django project bootstrap, Episode model with status tracking, admin interface — [plan](doc/plans/step-01-submit-episode.md), [feature](doc/features/step-01-submit-episode.md), [session](doc/sessions/2026-03-09-step-01-submit-episode.md)
