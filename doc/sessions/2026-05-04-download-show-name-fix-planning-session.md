# Download show_name + published_at planning session

**Date:** 2026-05-04

**Session ID:** unavailable

## Summary

Planning session that turned issue #111 into a three-layer plan:
(1) extract a real `show_name` in fetch_details and persist it on the
Episode; (2) plumb `published_at` from the aggregator candidates
through to the download agent so it can match by `(title, published_at)`;
(3) update the download agent's system prompt to recognize a
hostname-shaped `show_name` as a degraded signal and prefer the
date-based match. The user accepted bundling all three into one PR
with no backfill on the new model field, since the project is pre-prod.

## Detailed conversation

> **Agent-orchestrated session.** This planning session was launched
> by a parent Claude Code (Conductor) agent rather than directly by
> the user. The implementation agent that produced this transcript
> never received the user's verbatim wording — only a summarized brief
> from the parent agent. Per AGENTS.md's "Agent-orchestrated sessions"
> convention, the section below uses `### Parent agent (orchestrator)`
> instead of `### User`. The parent-agent's verbatim launching prompt
> could not be recovered from session logs and is therefore left
> unavailable; the substance of the brief is summarized in prose
> rather than fabricated as a quote.

### Parent agent (orchestrator)

*Verbatim launching prompt unavailable.* Substance of the brief
relayed to the planning agent: surface issue #111 — the canonical ARD
Sounds episode submitted in the PR #109 test plan goes to `FAILED`
even though fyyd carries a clean enclosure URL for it. Two contributing
factors: (a) `_show_name` falls back to URL host (`www.ardsounds.de`)
and never matches a real broadcast title; (b) the download agent
prompt encourages strict show matches. Produce a plan.

### Assistant

Worked through the failure mode in `episodes/downloader._show_name`
and the download agent system prompt. Confirmed via PR #109 test logs
that the agent rejected every candidate with the message
*"Keiner der gefundenen Podcast-Episoden aus dem Index passt zum Titel
oder der Show www.ardsounds.de"*. Proposed three layers of fix:

1. Real `show_name` source of truth: new `Episode.show_name` field;
   `EpisodeDetails` extracts it from `og:site_name` / RSS title /
   JSON-LD; `_show_name` prefers it over the URL host.
2. `published_at` as a tiebreaker: add it to `EpisodeCandidate`,
   plumb pubdate through fyyd / iTunes / podcastindex parsers, surface
   it on `IndexCandidate` and in `DownloadDeps`.
3. Looser, hostname-aware prompt: explicitly tell the agent that when
   `show_name` looks like a hostname it should switch to a
   `(title, published_at)` match with ±1 day.

Considered alternatives:
- *Layer 3 alone* (just relax the prompt) — rejected: fragile, the
  LLM still has nothing to match on when the publisher's hostname is
  the only signal it has.
- *Layer 1 alone* (extract show_name, leave prompt strict) — rejected:
  the prompt's exact-match wording would still bite when the publisher's
  show name doesn't appear verbatim on aggregator pages.
- *Backfill `show_name` for existing rows* — rejected per the user's
  pre-prod-data-freedom feedback (`feedback_reembed_ok_preprod.md`):
  full Postgres regen + re-ingest is the supported upgrade path.

### Parent agent (orchestrator)

*Verbatim relay unavailable.* Decisions communicated through the
parent agent:
- Bundle all three layers in one PR.
- Add a new model field (no backfill).
- Manual verification belongs in the PR description, not run by the
  implementation agent.
- Staleness against `main` is verified.

### Assistant

Captured the decisions, drafted this plan document, and queued the
implementation agent to execute it on a fresh branch
(`rafacm/download-show-name-fix`).
