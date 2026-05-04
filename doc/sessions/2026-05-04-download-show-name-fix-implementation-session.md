# Download show_name + published_at implementation session

**Date:** 2026-05-04

**Session ID:** unavailable

## Summary

Implementation session for the three-layer fix planned in
`doc/plans/2026-05-04-download-show-name-fix.md`: real `show_name`
source of truth, `published_at` plumbing through aggregators, and an
updated download agent prompt that handles hostname-shaped show names.
Carried out on branch `rafacm/download-show-name-fix`. All 384 tests
pass.

## Detailed conversation

> **Agent-orchestrated session.** This implementation session was
> launched by a parent Claude Code (Conductor) agent rather than
> directly by the user — the parent authorized the parallel session
> and handed the implementation agent a summarized brief, not a
> user-authored prompt. Per AGENTS.md's "Agent-orchestrated sessions"
> convention, the section below uses `### Parent agent (orchestrator)`
> instead of `### User`. The parent-agent's verbatim launching prompt
> could not be recovered from session logs and is therefore left
> unavailable; the substance of the brief is summarized in prose
> rather than fabricated as a quote.

### Parent agent (orchestrator)

*Verbatim launching prompt unavailable.* Substance of the brief
relayed to the implementation agent: implement issue #111. Verify
staleness of the headline lines first (`_show_name`,
`Episode.show_name`, `EpisodeDetails`, `EpisodeCandidate`, the three
aggregator `_candidate()` methods). Then carry out the three-layer
plan: add `Episode.show_name` (no backfill) + extract via
fetch_details; add `published_at` to `EpisodeCandidate` + plumb
through fyyd / iTunes / podcastindex; relax the download agent prompt
to handle hostname-shaped show names. Manual verification belongs in
the PR body. Document and PR via the project's normal flow.

### Assistant

**Staleness check.** Read each headline file. Confirmed:
- `episodes/downloader._show_name` still falls back to URL host.
- `Episode.show_name` was absent (`published_at` already present).
- `EpisodeDetails` did not extract `show_name`.
- `EpisodeCandidate` had no `published_at` field.
- None of fyyd / iTunes / podcastindex `_candidate()` parsed pubdate.

Plan still applies in full.

**Branch.** Created `rafacm/download-show-name-fix` off the worktree's
main equivalent.

**Layer 1 — `show_name`.**
- Added `show_name = CharField(max_length=255, blank=True, default="")`
  to `Episode`.
- Generated `episodes/migrations/0025_episode_show_name.py` via
  `uv run python manage.py makemigrations`.
- Added `show_name: str | None = None` to `EpisodeDetails` in
  `episodes/agents/fetch_details.py`. Updated the system prompt to
  enumerate the extraction sources (`og:site_name`,
  `application-name`, RSS `<channel><title>`, JSON-LD
  `isPartOf.name` / `partOfSeries.name`, visible publisher heading)
  and to forbid using the URL hostname or company name.
- Updated `episodes/fetch_details_step.py:_apply_details` to persist
  `show_name` only when the agent's value is non-empty (additive
  semantics — never wipe a previously-good value or admin edit on a
  partial re-run).
- Updated `episodes/downloader._show_name` to prefer
  `episode.show_name` and fall back to URL host.

**Layer 2 — `published_at`.**
- Added `published_at: date | None = None` to `EpisodeCandidate` in
  `episodes/podcast_aggregators/base.py`.
- fyyd: added `_parse_pubdate(raw)` accepting fyyd's documented
  `"YYYY-MM-DD HH:MM:SS"` plus ISO 8601 / `T`-separated / bare-date
  variants. Logs a warning and returns `None` on unparseable input —
  never raises.
- iTunes: added `_parse_release_date(raw)` using `datetime.fromisoformat`
  after replacing trailing `Z` with `+00:00`.
- podcastindex: added `_parse_date_published(raw)` accepting `int`,
  `float`, or numeric string Unix epoch seconds. Rejects `bool`
  (subclass of `int`) explicitly.
- All three log + return `None` on missing / malformed input. None
  drops the candidate.
- Added `published_at: date | None = None` to `DownloadDeps`.
- Added `published_at: date | None = None` to `IndexCandidate` in
  `episodes/agents/download_tools.py` and propagated it from each
  `EpisodeCandidate` in `lookup_podcast_index`.
- Updated `episodes/agents/download._run_agent_async` and
  `run_download_agent` signatures to accept `published_at: date | None`,
  forwarded into `DownloadDeps`.
- Updated `episodes/downloader.download_episode` to pass
  `episode.published_at` to `run_download_agent`.

**Layer 3 — prompt update.**
- Surfaced `Published: {published_at}` in the agent context block.
- Replaced the strict "if a candidate looks right" wording with a
  detailed candidate-picking section that:
  - Tells the agent to detect hostname-shaped `Show` values (contain
    `.` and no spaces) and switch to `(title, published_at)` matching.
  - Defines a "strong match" as ~equal title plus `published_at` ±1
    day.
  - Falls back to title similarity alone when `Published` is unknown.
  - Keeps the existing real-show-title path for the well-behaved case.

**Tests added.**
- `episodes/tests/test_models.py` — `show_name` blank by default;
  persists when set.
- `episodes/tests/test_podcast_aggregators.py` — for each of fyyd /
  iTunes / podcastindex: pubdate parsed correctly; missing pubdate
  returns `None`; malformed pubdate returns `None` without dropping
  the candidate.
- `episodes/tests/test_download.py` — `ShowNameTests`: `_show_name`
  returns `episode.show_name` when set; falls back to host; returns
  `""` for a URL with no host.

**Test run.** `uv run python manage.py test` — 384 tests passing.
`uv run python manage.py makemigrations --check --dry-run` — no
further migrations needed.

**Documentation.** Wrote plan, feature, planning session, and this
implementation session under `doc/`. Added a CHANGELOG entry under
`## 2026-05-04`.

**Manual verification.** Not run by the implementation agent —
included as a checklist in the PR body per the user's instruction.
The reviewer will exercise the canonical ARD Sounds URL on a live
ASGI worker with provider keys configured.

**PR.** Created against `main` with rebase merge strategy. Title:
"Plumb show_name + published_at through download cascade (closes
#111)". Body includes the manual verification checklist plus a
short summary of the three layers.
