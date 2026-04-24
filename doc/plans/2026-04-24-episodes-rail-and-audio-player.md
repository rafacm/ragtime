# Episodes right rail + audio player

**Date:** 2026-04-24

## Context

Following PR #95 (first working version of Scott, RAGtime's strict-RAG jazz podcast chatbot), the follow-up comment https://github.com/rafacm/ragtime/pull/95#issuecomment-4283742043 enumerates deferred work. Point 1 (Django-backed `ThreadList` with rename / delete / auto-titles) is already implemented — `frontend/src/threadAdapter.ts` uses `useRemoteThreadListRuntime` against `/chat/api/conversations/*` and `generate-title/` exists.

This plan covers two specific UI gaps the user wants to close next:

1. **Discoverability of the ingested corpus** — today users have no way to see which podcast episodes Scott actually knows about. A collapsible right rail will list all `status=READY` episodes.
2. **Listening alongside reading** — Scott cites `[N]` markers but users can't hear the source. A persistent "now playing" audio player at the bottom of the chat pane will appear when a user triggers playback (from a chunk row or an episode card), with minimize and close.

Out of scope (tracked for later follow-up PRs per the comment): inline `[N]` chip rendering in assistant text, episode deep-link pages, markdown rendering, rate limiting, evals.

## Locked design decisions

| # | Decision |
|---|---|
| 1 | **Episodes UI**: collapsible right `<aside>` (w-80 = 320px when open; 40px icon strip when collapsed). Default collapsed on first load. |
| 2 | **Audio player**: docked at the bottom of `<main>` (the chat pane). Rendered only when a track is active. Supports expand/minimize and close (close stops playback and unmounts the bar). |
| 3 | **Chunk-row click**: each row in the existing `SearchChunksDisplay` card becomes clickable → opens/seeks the player to `start_time`. Inline `[N]` chips in assistant text are deferred to a separate citation-polish PR. |
| 4 | **Episode-card click** in the right rail: plays from `0:00`. No "scope the chat to this episode" behaviour in this PR. |

## Implementation steps

### Backend

1. **Add `audio_url` to the Qdrant payload** — `episodes/embedder.py`: extend `_build_payloads()` with a new `episode_audio_url` key. Compute as `episode.audio_url or (episode.audio_file.url if episode.audio_file else "")`.
2. **Re-embed the existing corpus** — use the Django admin's existing "Reprocess" action with "embedding" as the starting step. No new management command needed.
3. **Enrich `ChunkSearchResult`** — `episodes/vector_store.py`: add `episode_audio_url: str`; read from the payload in `QdrantVectorStore.search()`.
4. **Forward new fields in `search_chunks`** — `chat/agent.py`: add `episode_id`, `episode_audio_url`, `episode_image_url` to the tool's returned dict.
5. **Episodes JSON endpoint** — `GET /episodes/api/episodes/` → READY episodes ordered by `published_at DESC` (nulls last), fields: `id, title, duration, published_at, audio_url (with audio_file.url fallback), image_url, description (truncated to 280)`. Optional `?limit=`.
6. **Tests** — new `episodes/tests/test_api.py`; extend `episodes/tests/test_embed.py` with `episode_audio_url` payload tests (including `audio_file` fallback); extend `chat/tests.py` shape test and chunk factory.

### Frontend

7. **Shared audio-player state** — new `frontend/src/audioPlayer.tsx`: `AudioPlayerProvider` + `useAudioPlayer()` hook wrapping one `HTMLAudioElement`. API: `play(track, atSec)`, `pause`, `resume`, `seek`, `minimize`, `expand`, `close`.
8. **`AudioPlayerBar`** — new `frontend/src/audioPlayerBar.tsx`: renders when a track is active; expanded (thumb + title + seek + play/pause + minimize + close) and minimized (title + play/pause + expand + close) modes.
9. **`EpisodesPanel` right rail** — new `frontend/src/episodesPanel.tsx`: fetches `/episodes/api/episodes/`, renders a collapsible rail with episode cards. Clicking an episode plays from 0:00.
10. **Make chunk rows clickable** — extend `RetrievedChunk` TS type with `episode_id`, `episode_audio_url`, `episode_image_url`. `<li>` gets `role="button"`, click/keyboard handlers → `audioPlayer.play({...}, start_time)`. Falls back to plain text when `audio_url` is empty.
11. **Layout changes** — wrap `App` in `<AudioPlayerProvider>`; add right aside + toggle button in main header; `AudioPlayerBar` sits at bottom of `<main>`.
12. **Shared util** — extract `formatTime()` into `frontend/src/time.ts`.

### Docs / changelog

13. `doc/plans/…`, `doc/features/…`, `doc/sessions/…`, `CHANGELOG.md` entry under `## 2026-04-24`. No `.env.sample` or `configure.py` changes.

## Critical files to modify / create

- `episodes/embedder.py` — add `episode_audio_url` to `_build_payloads()`.
- `episodes/vector_store.py` — extend `ChunkSearchResult`; read `episode_audio_url` from payload in `search()`.
- `chat/agent.py` — forward new fields in tool result.
- `episodes/views.py`, `episodes/urls.py` — new `/episodes/api/episodes/` endpoint.
- `episodes/tests/test_api.py` (new), `episodes/tests/test_embed.py`, `chat/tests.py` — tests.
- `frontend/src/audioPlayer.tsx`, `audioPlayerBar.tsx`, `episodesPanel.tsx`, `time.ts` (new).
- `frontend/src/chat.tsx` — types, layout, wire provider, clickable rows.

## Risks / open decisions

1. **Empty `audio_url`** — embed payload and endpoint both fall back to `audio_file.url`; frontend disables click when both are empty.
2. **Range requests on hosted media** — local `MEDIA_URL` supports seeking. In prod behind CDN/S3, confirm signed URLs allow `Range`.
3. **Default rail state** — starting collapsed preserves chat width on ~1280px laptops.
4. **Episode count growth** — unpaginated is fine for 100s; past ~2k switch to cursor pagination.

## Verification

**Automated**
- `uv run python manage.py test chat episodes` — green.
- `cd frontend && npm run build` — TypeScript + Vite green.
- `uv run python manage.py check` — green.

**Manual**
1. Populate the `episode_audio_url` payload on existing points via the Django admin: `/admin/episodes/episode/` → select READY episodes → "Reprocess" action → "embedding" step.
2. `uv run uvicorn ragtime.asgi:application --reload` + `cd frontend && npm run dev`.
3. Sign in, toggle the right rail, click an episode → bar appears at 0:00.
4. Ask a question triggering `search_chunks`, click a chunk row → player seeks to `start_time` (switches episode if different; no reload if same).
5. Minimize → shrinks to ~32px; close → bar disappears, audio stops.
6. Resize to <768px → right aside hidden; player bar still works.
7. Keyboard: Tab into a chunk row, Enter → same as click.
