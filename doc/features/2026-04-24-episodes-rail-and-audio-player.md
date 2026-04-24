# Episodes right rail + audio player

**Date:** 2026-04-24

## Problem

Two gaps in the Scott chat UI, carried over from the deferred-work list in https://github.com/rafacm/ragtime/pull/95#issuecomment-4283742043:

1. Users had no way to see which podcast episodes Scott could actually answer about. The only browsable list of ingested episodes was the Django admin changelist, which is staff-only.
2. Scott cites `[N]` markers backed by chunk timestamps, but nothing played the audio. Users could read about a moment in an episode without being able to hear it.

## Changes

### Backend

- **Qdrant payloads now include `episode_audio_url`** (`episodes/embedder.py`). Computed at embed time as `episode.audio_url or (episode.audio_file.url if episode.audio_file else "")`. To refresh existing points with the new key, use the Django admin's "Reprocess" action on selected episodes and pick "embedding" as the starting step — `QdrantVectorStore.delete_by_episode()` already wipes prior points at the start of each embed, so the step is idempotent.
- **`ChunkSearchResult` gains `episode_audio_url: str`** (`episodes/vector_store.py`). `QdrantVectorStore.search()` reads it from the Qdrant payload — no DB join.
- **Scott's `search_chunks` tool forwards `episode_id`, `episode_audio_url`, `episode_image_url`** to the frontend (`chat/agent.py`). These fields were already in `ScottState.retrieved_chunks` but not in the tool's return dict, so the chat UI never saw them.
- **New episodes JSON endpoint** `GET /episodes/api/episodes/` (`episodes/views.py`, `episodes/urls.py`). Login-required, returns all READY episodes ordered by `published_at DESC` with NULLs last. Fields: `id, title, duration, published_at, audio_url, image_url, description` (truncated to 280 chars). Optional `?limit=<1..500>`.

### Frontend

- **Shared audio player state** — `frontend/src/audioPlayer.tsx` exports `AudioPlayerProvider` + `useAudioPlayer()`. The provider owns a single `HTMLAudioElement` and exposes `play(track, atSec)`, `pause`, `resume`, `seek`, `minimize`, `expand`, `close`. When `play()` is called with the same audio URL already loaded, it seeks without reloading.
- **`AudioPlayerBar` component** (`frontend/src/audioPlayerBar.tsx`) — docked at the bottom of the chat pane. Renders only when `currentTrack` is non-null. Expanded mode (~60px): thumbnail, title, seek `<input type="range">`, play/pause, times, minimize, close. Minimized mode (~32px): title + play/pause + expand + close.
- **Right rail** — `frontend/src/episodesPanel.tsx` is a collapsible `<aside>` hosting the episodes list. Collapsed state is a 40px icon strip; expanded is `w-80` (320px). Defaults to collapsed so the chat pane keeps its default width on 1280px laptops. Each episode card plays from `0:00` on click.
- **Chunk rows in `SearchChunksDisplay` became clickable** (`frontend/src/chat.tsx`). Each row is now `role="button" tabIndex={0}` with `onClick` and `onKeyDown` (Enter/Space) → `audioPlayer.play({episodeId, audioUrl, title, imageUrl}, start_time)`. Rows with no `audio_url` fall back to plain text.
- **`formatTime()`** moved to `frontend/src/time.ts` and is shared across the chat card, the bar, and the episodes rail. Extended to handle hours (e.g. `1:02:03`).

## Key parameters

| Parameter | Value | Rationale |
|---|---|---|
| Right rail default | Collapsed | Preserves chat width on 1280px screens; left sidebar already takes 320px |
| Right rail expanded width | `w-80` (320px) | Mirrors the left sidebar |
| Right rail collapsed width | 40px | Enough for a single icon toggle |
| Player bar expanded height | ~60px | Room for thumbnail + seek bar |
| Player bar minimized height | ~32px | Thin "now playing" strip |
| Episodes endpoint default limit | Unbounded | ~100s of episodes; switch to pagination past 2k |
| Episodes endpoint max `?limit=` | 500 | Safety clamp for the unbounded case |
| Description preview chars | 280 | Matches a tweet-sized preview in the rail |

## Verification

**Automated**
- `uv run python manage.py test` — 298 tests pass (8 new in `episodes/tests/test_api.py`, 3 new in `episodes/tests/test_embed.py` covering `episode_audio_url` and its `audio_file` fallback; `chat/tests.py` factory + shape test extended).
- `cd frontend && npm run build` — `tsc --noEmit` + Vite build clean.
- `uv run python manage.py check` — clean.

**Manual**
1. Ensure Qdrant payloads have the new `episode_audio_url` key: open `/admin/episodes/episode/`, select all READY episodes, run the "Reprocess" action, and pick "embedding" as the starting step.
2. Start services: `uv run uvicorn ragtime.asgi:application --reload` in one terminal; `cd frontend && npm run dev` in another.
3. Sign in at `/accounts/login/`.
4. Toggle the right rail from the header button in the chat pane → episodes list renders (READY only, newest first).
5. Click an episode card → bottom bar appears, plays from `0:00`, thumbnail/title/duration visible.
6. Ask a question that triggers `search_chunks` (e.g. "What do they say about Kind of Blue?"). In the assistant's search-chunks card, click a chunk row → player seeks to the row's `start_time` (switches episode if different; no reload if same episode).
7. Minimize → shrinks to ~32px; close → bar disappears, audio stops.
8. Resize to <768px → right aside hidden, player bar still visible and functional.
9. Keyboard: Tab into a chunk row, press Enter → same behaviour as click.

## Files modified

- `episodes/embedder.py` — add `episode_audio_url` to `_build_payloads()` with `audio_file.url` fallback.
- `episodes/vector_store.py` — add `episode_audio_url` to `ChunkSearchResult`; read from payload in `search()`.
- `episodes/views.py` — new `api_episode_list` view + helpers (`_serialize_episode`, `_episode_audio_url`).
- `episodes/urls.py` — mount `/api/episodes/`.
- `episodes/tests/test_api.py` (new) — 8 tests (auth gating, status filter, ordering with NULLs, limit, field shape, `audio_file` fallback, description truncation, invalid limit).
- `episodes/tests/test_embed.py` — 3 new tests for `episode_audio_url` and its fallback.
- `chat/agent.py` — forward `episode_id`, `episode_audio_url`, `episode_image_url` in `search_chunks` tool output.
- `chat/tests.py` — extend chunk factory + `ChunkSearchResultShapeTests` with `episode_audio_url`.
- `frontend/src/audioPlayer.tsx` (new) — `AudioPlayerProvider` + `useAudioPlayer()`.
- `frontend/src/audioPlayerBar.tsx` (new) — bottom "now playing" bar with expanded/minimized modes.
- `frontend/src/episodesPanel.tsx` (new) — collapsible right rail.
- `frontend/src/time.ts` (new) — shared `formatTime()` helper.
- `frontend/src/chat.tsx` — wrap in `<AudioPlayerProvider>`, add right aside + header toggle, clickable chunk rows, use shared `formatTime`.
