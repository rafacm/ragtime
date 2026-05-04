# Download show_name + published_at fix (issue #111)

**Date:** 2026-05-04

## Summary

Tighten the download agent's index-candidate matching for non-English shows
whose extracted show name is empty by fixing the root cause (no `show_name`
extraction in fetch-details) rather than papering over it in the agent
prompt alone.

## Problem

Submitting `https://www.ardsounds.de/episode/urn:ard:episode:fdcf93eef8395b35/`
fails the download step even though fyyd carries a clean enclosure URL for
the episode. Two factors interact:

1. **No `show_name` source of truth.** `Episode` has no `show_name` field
   and `fetch_details` doesn't extract one. `episodes/downloader._show_name`
   falls back to the URL host (`www.ardsounds.de`).
2. **Strict match in the agent prompt.** With `show_name = "www.ardsounds.de"`
   on the episode and `show_name = "Zeitzeichen"` on every fyyd candidate,
   the agent rejects every candidate and the episode goes to `FAILED`.

## Plan

Three layers, bundled into one PR.

### Layer 1 — real `show_name`

- Add `Episode.show_name = CharField(max_length=255, blank=True, default="")`.
  Generate Django migration. No backfill (project is pre-prod).
- Extend `EpisodeDetails` schema in `episodes/agents/fetch_details.py` with
  `show_name: str | None = None`. Update the system prompt to extract
  `show_name` from `<meta property="og:site_name">`,
  `<meta name="application-name">`, RSS `<channel><title>`, JSON-LD
  `isPartOf.name`, and the visible publisher / show heading.
- Persist `EpisodeDetails.show_name → Episode.show_name` in
  `episodes/fetch_details_step.py` only when the value is non-empty (don't
  wipe a previously-good value or a user edit on a re-run that fails to
  extract).
- Update `episodes/downloader._show_name(episode)` to prefer
  `episode.show_name`, with the URL host as a defense-in-depth fallback.

### Layer 2 — date as a tiebreaker

- Add `published_at: date | None = None` to
  `episodes/podcast_aggregators/base.EpisodeCandidate`.
- Plumb pubdate through each aggregator's `_candidate()`:
  - **fyyd**: `item["pubdate"]` (ISO 8601 string like
    `"2024-08-30 04:00:00"`) → `date`.
  - **iTunes**: `item["releaseDate"]` (ISO 8601 datetime) → `date`.
  - **podcastindex**: `item["datePublished"]` (Unix epoch seconds) →
    `date`.
  - On parse failure: leave `published_at = None` and log a warning. Do
    NOT drop the candidate.
- Pass `episode.published_at` through `DownloadDeps` and the download
  agent's prompt template.
- Surface `published_at` on each `IndexCandidate` returned by
  `lookup_podcast_index`.

### Layer 3 — looser, hostname-aware prompt

Update the download agent system prompt in `episodes/agents/download.py`:

> `show_name` may be a publisher hostname rather than the broadcast title
> (e.g. `www.ardsounds.de` instead of `Zeitzeichen`). When `show_name`
> looks like a hostname (contains `.` and no spaces), do NOT require an
> exact string match against the candidate's `show_name`. Instead, prefer
> matching candidates by `(title, published_at)`. A candidate is a strong
> match when its title closely matches the episode title and its
> `published_at` is within ±1 day of the episode's `published_at`.

## Decisions

- **Bundle all three layers**: Layer 1 alone leaves the prompt strict;
  Layer 3 alone papers over the missing field. Doing all three in one
  commit gives the agent both real data and the right matching policy.
- **Add new model field, no backfill**: `Episode.show_name` is a new
  `CharField` with empty default. Pre-prod data per
  `feedback_reembed_ok_preprod.md`.
- **Manual verification in PR description**: requires a live ASGI server,
  provider keys, and the canonical ARD episode. Not run by the
  implementation agent — flagged in the PR body for the reviewer.

## Test plan

- Each aggregator's `_candidate()` populates `published_at` from a canned
  payload.
- Each aggregator handles missing / malformed pub dates gracefully
  (returns `published_at=None`, doesn't drop the candidate).
- `_show_name(episode)` returns `episode.show_name` when set, falls back
  to URL host otherwise, returns `""` for a URL with no host.
- `Episode.show_name` is blank by default and persists when set.
- `manage.py makemigrations --check` passes (no further migrations
  needed).
- Full test suite passes via `uv run python manage.py test`.

## Files touched

- `episodes/models.py` — add `show_name` field.
- `episodes/migrations/0025_episode_show_name.py` — new migration.
- `episodes/agents/fetch_details.py` — `EpisodeDetails.show_name` +
  prompt update.
- `episodes/fetch_details_step.py` — persist `show_name` when non-empty.
- `episodes/downloader.py` — `_show_name` cascade; pass `published_at`
  to the agent.
- `episodes/podcast_aggregators/base.py` — `EpisodeCandidate.published_at`.
- `episodes/podcast_aggregators/{fyyd,itunes,podcastindex}.py` — parse
  pubdate, log + skip on failure.
- `episodes/agents/download_deps.py` — `DownloadDeps.published_at`.
- `episodes/agents/download_tools.py` — `IndexCandidate.published_at`,
  surface in `lookup_podcast_index` return value.
- `episodes/agents/download.py` — extend prompt, plumb `published_at`
  through `_run_agent_async` / `run_download_agent`.
- `episodes/tests/test_models.py` — `show_name` blank default + persistence.
- `episodes/tests/test_podcast_aggregators.py` — three pubdate parse
  scenarios per aggregator.
- `episodes/tests/test_download.py` — `_show_name` cascade tests.
- `doc/plans/2026-05-04-download-show-name-fix.md` — this file.
- `doc/features/2026-05-04-download-show-name-fix.md` — implementation doc.
- `doc/sessions/2026-05-04-download-show-name-fix-planning-session.md`
- `doc/sessions/2026-05-04-download-show-name-fix-implementation-session.md`
- `CHANGELOG.md` — entry under `## 2026-05-04`.
