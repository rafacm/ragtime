# Episodes right rail + audio player — Planning session

**Date:** 2026-04-24

**Session ID:** 8a578668-0d3e-45db-bcc8-3f503c2a4e2e

## Summary

Planned the follow-up PR to Scott (#95) that closes two user-visible gaps: surfacing the list of ingested podcast episodes in the UI, and letting users play the source audio when they click a citation. Shape of the final design: a collapsible right rail for the episodes list, a persistent "now playing" bar at the bottom of the chat pane that only appears when audio is active (with close + minimize), and clickable chunk rows in the existing `SearchChunksDisplay` card that seek the player to the chunk's `start_time`. Deferred the `[N]`-as-chip rendering in assistant text to a separate citation-polish PR.

## Detailed conversation

### User

Let's revisit this follow up comment https://github.com/rafacm/ragtime/pull/95#issuecomment-4283742043
I believe point 1 we implemented already in a previous PR. Given the current UI which I attach, let's first discus the following points:
1. how do we show to the user the available podcast episodes that have been ingested? Options: add a right column that lists the episodes?
2. where do we place the podcast audio player that will be triggered when the user clicks on a response reference?

### Assistant

Fetched the PR #95 follow-up comment via `gh api` and the PR's own body to understand what shipped and what was deferred. Confirmed the user's recollection: point 1 (Django-backed `ThreadList` with rename / delete / auto-titles) is already implemented — `frontend/src/threadAdapter.ts` uses `useRemoteThreadListRuntime` against `/chat/api/conversations/*`, and the LLM-powered `generate-title/` endpoint exists.

Launched two parallel Explore agents to map the state of the codebase:

- **Chat frontend & citation rendering** — confirmed the chat UI is a 2-column flexbox in `frontend/src/chat.tsx:281-315` (320px left `<aside>` with conversations + flex-1 `<main>`). Found an existing `SearchChunksDisplay` component at lines 43-108 that renders each `search_chunks` tool call as a collapsible card with chunk citation, episode title, and start/end times. The `formatTime()` helper was local to `chat.tsx`. A single Vite entry point (`chat.tsx` → `#scott-root`) means any new React content can simply be a child of the existing app tree — no second island needed.
- **Episode data & what's exposed** — confirmed `Episode` has `audio_url`, `audio_file`, `duration`, `published_at`, `image_url`, with `status=READY` indicating full ingestion. `Chunk.start_time` and `end_time` are floats in seconds, precise enough for audio seeking. `ChunkSearchResult` already carries `episode_id`, `episode_title`, `episode_url`, `episode_image_url`, `start_time`, `end_time` but NOT `audio_url`, and the embedder's `_build_payloads()` does not include it in Qdrant payloads. No user-facing episodes endpoint exists — `episodes/urls.py` only has Wikidata admin helpers.

Confirmed the two locked decisions were: (a) UI already has ChunkSearchResult data in the card but needs `audio_url` and `episode_id`; (b) citations are not yet inline chips in text — that's a separate concern, tracked by the "citation polish" bucket of the same follow-up comment.

Presented a trade-off matrix covering four options for the episodes UI (permanent right column / collapsible right rail / browse-episodes modal / second section in left sidebar) and four for the audio player (inline per card / persistent bottom bar / top of right rail / floating mini-player). My recommendations: collapsible right rail for episodes and a bottom bar for the player — the bar matches the Spotify / Apple Podcasts mental model where any citation click funnels into one global player. Cited trade-offs: horizontal space cost, discoverability, multi-citation playback semantics, mobile fitness.

### User

(via AskUserQuestion) Answered "Collapsible right rail (Recommended)" for the episodes panel. Did not pick an option for the audio player — requested clarification instead.

### Assistant

Offered five clarification angles on the audio player decision: interaction model (auto-play vs seek-and-wait), scope (single episode vs queue), persistence across thread switches, visual density of transport controls, and whether mobile matters. Asked which was driving the hesitation.

### User

Let's go for option 1 but the player should only be shown when playing an episode and it should be possible to close it and minimize it.

### Assistant

Locked in: bottom-bar player, shown only when playing, with minimize + close. Followed up with one more scoping question to nail down the citation-click behaviour and the rail-click behaviour, since both feed into the same player state:

- Citation click options: (a) chunk rows only, (b) both `[N]` chips in text AND chunk rows, (c) only `[N]` chips.
- Rail click options: (a) play from 0:00, (b) scope next question to this episode, (c) both with separate controls.

### User

(via AskUserQuestion) Chose "Chunk row click → play from chunk start (Recommended)" and "Play episode from 00:00 (Recommended)".

### Assistant

With all four decisions locked, spawned a Plan agent to design the implementation. Gave the agent explicit locked decisions, the key code paths from Phase-1 exploration, and the verification expectations. The Plan agent returned a thirteen-step plan covering backend (Qdrant payload changes, re-embed handling, DB vs payload trade-off, new endpoint, tests), frontend (provider, bar, panel, clickable rows, layout wiring, shared util), docs, and verification.

Verified two critical assumptions the Plan agent flagged by reading real code:

- `chat/agent.py:146-157` confirmed that `search_chunks` hand-rolls its returned dict rather than returning `asdict(ChunkSearchResult)`, so adding fields to the dataclass alone doesn't reach the frontend — we must also extend the dict.
- `episodes/models.py:32` confirmed `audio_url` is a blank-default `URLField`, so the `audio_file.url` fallback is real (blank rows exist).

Wrote the final plan to `/Users/rafa/.claude/plans/let-s-revisit-this-follow-peaceful-dewdrop.md`. Initially recommended a DB-join approach for surfacing `audio_url` in `ChunkSearchResult` to avoid re-embedding.

### User

(ExitPlanMode rejection) Regarding Decision: "DB-join over Qdrant-payload backfill — avoids re-embedding and keeps audio_url authoritative in Postgres. Document this in a short comment.". We can re-embed. This is not an issue this app is still not in production.

### Assistant

Corrected the plan: dropped the DB-join workaround; added `episode_audio_url` directly to `_build_payloads()` and read it from the Qdrant payload in `search()`. Added a new `episodes/management/commands/reembed_all.py` step that walks all READY episodes, flips status to EMBEDDING, and re-runs the existing `embed_episode()` step. Saved a feedback memory (`feedback_reembed_ok_preprod.md`) so future sessions don't propose DB-join workarounds for pre-production schema changes. Re-numbered the steps, updated the verification section to include `manage.py reembed_all`, and flagged the `reembed_all`-vs-live-ingestion race as a risk (command must skip non-READY episodes).

### User

(ExitPlanMode approval) Plan approved. Autonomous mode activated for implementation.
