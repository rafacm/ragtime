# Download show_name + published_at fix

**Date:** 2026-05-04

## Problem

The Download agent rejected every fyyd / podcastindex candidate for the
canonical ARD Sounds test episode
(`https://www.ardsounds.de/episode/urn:ard:episode:fdcf93eef8395b35/`)
even though fyyd had a clean Akamai enclosure URL for it. Two factors
combined:

1. `Episode` had no `show_name` field. `episodes/downloader._show_name`
   fell back to the URL host (`www.ardsounds.de`), which never matches
   a real broadcast title (`Zeitzeichen`).
2. The download agent's system prompt encouraged a strict show / title
   match — so the LLM played it safe and rejected the candidate set.

## Changes

Three coordinated layers, single commit set.

### Layer 1 — `Episode.show_name` source of truth

- New `Episode.show_name = CharField(max_length=255, blank=True, default="")`.
- Migration `0025_episode_show_name`. No backfill (pre-prod).
- `EpisodeDetails` Pydantic schema in `episodes/agents/fetch_details.py`
  gains `show_name: str | None = None`. The system prompt instructs the
  agent to extract from (in order): `<meta property="og:site_name">`,
  `<meta name="application-name">`, RSS `<channel><title>`, JSON-LD
  `isPartOf.name` / `partOfSeries.name`, then the visible publisher
  heading. Hostnames and company names are explicitly out of scope.
- `episodes/fetch_details_step.py` persists
  `EpisodeDetails.show_name → Episode.show_name` only when the agent's
  value is non-empty. A re-run that fails to extract a show name leaves
  the previously-good value (or admin edit) in place.
- `episodes/downloader._show_name(episode)` cascades:
  `episode.show_name` → URL host → `""`. The URL host fallback stays as
  a defense-in-depth so the agent always receives some `show_name`
  context, but the agent prompt now treats hostname-shaped values as a
  degraded signal.

### Layer 2 — `published_at` as a tiebreaker

- `EpisodeCandidate` (in `episodes/podcast_aggregators/base.py`) gains
  `published_at: date | None = None`.
- Each aggregator now extracts a publication date and logs+returns
  `None` on missing / malformed input rather than dropping the candidate:
  - **fyyd**: parses `item["pubdate"]` (string,
    `"YYYY-MM-DD HH:MM:SS"` per fyyd docs; also handles ISO 8601 and
    bare `YYYY-MM-DD`).
  - **iTunes**: parses `item["releaseDate"]` (ISO 8601 datetime, e.g.
    `"2024-08-30T04:00:00Z"`).
  - **podcastindex**: converts `item["datePublished"]` (Unix epoch
    seconds, ints or numeric strings) to UTC date.
- `DownloadDeps` (in `episodes/agents/download_deps.py`) gains
  `published_at: date | None = None`.
- `IndexCandidate` in `episodes/agents/download_tools.py` gains
  `published_at: date | None = None` so the agent sees per-candidate
  dates inside `lookup_podcast_index` results.
- `episodes/downloader.download_episode` passes `episode.published_at`
  through to `run_download_agent` → `_run_agent_async` → `DownloadDeps`.

### Layer 3 — hostname-aware download agent prompt

`DOWNLOAD_SYSTEM_PROMPT` in `episodes/agents/download.py` now:

- Surfaces the episode's `Published` date alongside title / show.
- Tells the agent: when `Show` contains a `.` and no spaces (i.e. it
  looks like a hostname), treat it as a degraded signal — do NOT
  require exact string match on candidate `show_name`. Instead, prefer
  matching candidates by `(title, published_at)`, with a window of ±1
  day. When `Published` is unknown, fall back to title similarity alone.
- Real show titles still use the existing show-plus-title match.

## Key parameters

- `Episode.show_name max_length = 255` — comfortable for very long
  podcast titles (Apple Podcasts allows up to 255).
- Date match window: ±1 day. Looser than exact match (covers timezone
  drift between publisher and aggregator) but tighter than e.g. a
  week (avoids matching an unrelated re-broadcast).

## Verification

Tests:

```bash
uv run python manage.py test
# 384 tests pass.
```

Manual (post-deploy / pre-merge with reviewer — see PR body):

1. Submit `https://www.ardsounds.de/episode/urn:ard:episode:fdcf93eef8395b35/`
   via the admin "Submit episode" form.
2. Watch fetch_details populate `Episode.show_name = "Zeitzeichen"` (or
   similar).
3. Confirm download step reaches `READY` via the index path with
   `source="fyyd"`.
4. `dbos workflow steps <id>` shows `download_step` succeeded.
5. Smoke-test on one English episode (e.g. an iTunes-indexed show).
6. Smoke-test on an episode where fetch_details fails to extract a
   show name → confirm host-fallback path still works (agent reads
   the hostname-shaped show_name, switches to `(title, published_at)`
   match).

## Files modified

| Path | Summary |
|------|---------|
| `episodes/models.py` | Add `show_name` `CharField`. |
| `episodes/migrations/0025_episode_show_name.py` | New migration. |
| `episodes/agents/fetch_details.py` | Add `show_name` to `EpisodeDetails`; extend system prompt. |
| `episodes/fetch_details_step.py` | Persist `show_name` only when non-empty. |
| `episodes/downloader.py` | Cascade in `_show_name`; pass `published_at` through. |
| `episodes/podcast_aggregators/base.py` | Add `published_at` to `EpisodeCandidate`. |
| `episodes/podcast_aggregators/fyyd.py` | Parse `pubdate` → `date`. |
| `episodes/podcast_aggregators/itunes.py` | Parse `releaseDate` → `date`. |
| `episodes/podcast_aggregators/podcastindex.py` | Parse `datePublished` (epoch) → `date`. |
| `episodes/agents/download_deps.py` | Add `published_at` to `DownloadDeps`. |
| `episodes/agents/download_tools.py` | Add `published_at` to `IndexCandidate`; surface in tool output. |
| `episodes/agents/download.py` | Hostname-aware prompt; plumb `published_at`. |
| `episodes/tests/test_models.py` | `show_name` default + persistence. |
| `episodes/tests/test_podcast_aggregators.py` | Pubdate parse / missing / malformed for all three aggregators. |
| `episodes/tests/test_download.py` | `_show_name` cascade tests. |
| `CHANGELOG.md` | Entry under `## 2026-05-04`. |
