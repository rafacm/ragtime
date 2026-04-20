# Scott — RAG Chatbot

**Date:** 2026-04-20

## Problem

The project needed its first working version of **Scott**, the strict-RAG jazz podcast chatbot described in `README.md` and `doc/README.md`. The ingestion pipeline already populated Qdrant with citation-ready chunk metadata (episode title, URL, timestamps, language), but there was no chat app, no query-time retrieval helper, no streaming agent, and no UI. Scott is the user-facing payoff of everything upstream.

## Changes

### Retrieval

- `episodes/vector_store.py` gained `search_chunks(query, top_k, episode_id?, score_threshold?)` plus a `ChunkSearchResult` dataclass and a `QdrantVectorStore.search()` method that calls `query_points` with optional episode-id filter and score floor. The helper embeds the query with the configured `EmbeddingProvider`, returning populated dataclasses ready for citation.

### Agent

- New `chat/` Django app with `Conversation` and `Message` models (user FK, JSON content blobs, tool-call blobs) + admin-discoverable migration.
- `chat/agent.py` defines `ScottState` (cumulative `retrieved_chunks` registry + optional `conversation_id`), a lazily-built Pydantic AI `Agent` keyed by new `RAGTIME_SCOTT_*` settings, the `search_chunks_tool` (`@agent.tool`) that dedupes by `chunk_id`, assigns stable 1-indexed `[N]` labels, and returns a compact list for the LLM. A dynamic `@agent.instructions` callable injects the cumulative citation registry into every turn so the model always sees available labels.
- System prompt enforces strict-RAG contract: must call `search_chunks` before any factual answer, may call repeatedly, must cite with `[N]` markers matching tool results, must refuse if nothing relevant is found, must reply in the user's language.
- Agent exposed as an ASGI app via `agent.to_ag_ui(deps=StateDeps(ScottState()))` (AG-UI protocol — HTTP+SSE).

### Hosting

- `ragtime/asgi.py` replaced the default shim with a path-based dispatcher: `/chat/agent/` routes to the Pydantic AI AG-UI app (behind a custom auth middleware that parses the Django session cookie, validates the session store, and confirms `user.is_active`, rejecting unauthenticated requests with 401); everything else falls through to Django's standard ASGI app. Keeps the whole stack in a single Python process — no separate Starlette service, no Next.js runtime bridge.

### UI

- New `frontend/` Vite workspace (React 19, TypeScript, Tailwind 4 via `@tailwindcss/vite`). npm deps: `@ag-ui/client`, `@assistant-ui/react`, `@assistant-ui/react-ag-ui`, `react`, `react-dom`.
- `frontend/src/chat.tsx` instantiates `HttpAgent({ url: "/chat/agent/" })`, feeds it to `useAgUiRuntime`, and renders assistant-ui's `<Thread>` + `<ThreadList>` inside an `<AssistantRuntimeProvider>`. CSRF token is threaded from the cookie into both fetch requests and the AG-UI HttpAgent headers.
- `frontend/src/threadAdapter.ts` wires both assistant-ui adapters end-to-end:
  - `threadList` — lists conversations, creates new ones, and on switch loads the target thread's history and returns it as `{ messages: ThreadMessage[] }`, which assistant-ui applies to the current thread.
  - `history` — `append(item)` POSTs each turn's `ExportedMessageRepositoryItem` to `/chat/api/conversations/<id>/history/` (assistant-ui drives this automatically after each message), and `load()` returns the stored repository so mounting with an already-active thread restores it.
- Django-side shape: `Message.external_id`, `Message.parent_external_id`, and `Message.payload_json` preserve assistant-ui's message-tree identifiers so the repository round-trips cleanly. The history POST endpoint upserts on `(conversation, external_id)` — safe against duplicate appends caused by transient client retries.
- `chat/templates/chat/index.html` is the Django shell template that mounts `#scott-root` and loads the Vite bundle via `django-vite` tags.
- `chat/templates/registration/login.html` is a minimal `LoginView` template (no self-signup; admin-provisioned users only).

### Persistence endpoints

- `chat/views.py` exposes `chat_page` (`@login_required`) plus JSON endpoints:
  - `api_conversations` — GET list / POST create
  - `api_conversation_detail` — GET / PATCH title / DELETE
  - `api_conversation_history` — GET returns the full `ExportedMessageRepository`; POST appends one `ExportedMessageRepositoryItem`, upserting on `(conversation, external_id)` to tolerate client-side retries.
- All endpoints are `@login_required` and scoped to `request.user`; message payloads are stored verbatim in `payload_json` so the backend stays decoupled from assistant-ui's internal `ThreadMessage` shape.

### Settings & docs

- Added `RAGTIME_SCOTT_PROVIDER`, `RAGTIME_SCOTT_MODEL`, `RAGTIME_SCOTT_API_KEY`, `RAGTIME_SCOTT_TOP_K`, `RAGTIME_SCOTT_SCORE_THRESHOLD`, `LOGIN_URL`, `LOGIN_REDIRECT_URL`, `STATIC_ROOT`, `STATICFILES_DIRS`, and a `DJANGO_VITE` block to `ragtime/settings.py`. `chat` and `django_vite` added to `INSTALLED_APPS`. `.env.sample` and the configure wizard (`core/management/commands/_configure_helpers.py`) gained a Scott subsystem.
- `AGENTS.md` updated: Qdrant replaces the stale ChromaDB reference; Scott architecture section updated to reflect the AG-UI + assistant-ui topology; commands section now includes the frontend `npm` scripts.
- `doc/README.md` "How Scott Works" section rewritten around the tool-call loop, `[N]` citation contract, configuration table, and topology diagram.

### Tests

- `chat/tests.py` covers: `search_chunks` flag/threshold passthrough with faked embedder + store; agent refusal on empty retrieval (scripted via `FunctionModel`); citation integrity (every `[N]` in the assistant message maps to `ScottState.retrieved_chunks`); **cross-request `ScottState` isolation** (regression test guarding against a regressed singleton deps); auth gating on `/chat/` and the ASGI `/chat/agent/` mount; conversation lifecycle (create / list / history append / history replay / delete); history round-trip preserving the parent-id chain; idempotent duplicate append; `message.id` required; history endpoints scoped to the owning user.
- Existing `core.tests.test_configure` wizard tests updated with the new Scott subsystem prompts.

## Key parameters

| Parameter | Value | Why |
|---|---|---|
| `RAGTIME_SCOTT_TOP_K` | `5` | Enough breadth for multi-facet answers without blowing the context window. Matches typical RAG top-k defaults. |
| `RAGTIME_SCOTT_SCORE_THRESHOLD` | `0.3` | Drops clearly-irrelevant chunks (common with multilingual cosine at low similarity). Low enough not to starve the agent on narrow queries. |
| `RAGTIME_SCOTT_MODEL` | `gpt-4.1-mini` | Same default as every other LLM step in the project — cheap, fast, strong at tool-use. Swap to `gpt-4.1` for harder jazz knowledge questions if needed. |
| System prompt | `chat/agent.py:SCOTT_SYSTEM_PROMPT` | Enforces the six strict-RAG rules verbatim. Citation index discipline is backed by a unit test so drift is caught. |

## Verification

```bash
# Backend
uv sync
uv run python manage.py migrate
uv run python manage.py test chat        # 9 tests, all green
uv run python manage.py test              # full suite, 283 tests

# Frontend
cd frontend && npm install
cd frontend && npm run dev                # Vite HMR on :5173

# End-to-end (separate terminal)
uv run python manage.py runserver --noreload  # :8000, must be ASGI-aware
# Visit http://localhost:8000/chat/ → redirects to login
# Sign in with a user created via `manage.py createsuperuser`
# Ask: "What do the podcasts say about Kind of Blue?"
# Expect: streaming answer with [1], [2] markers; tool-call for search_chunks
# visible in the thread; citations map to real chunks.
```

**Manual acceptance:**
- Multilingual: ask in Spanish against an English-only corpus → Spanish answer, English citations.
- Refusal: ask about an artist not in the corpus → Scott says so, no guess.
- Auth gate: logged out, POST `/chat/agent/` → 401; GET `/chat/` → 302 to `/accounts/login/`.

## Files modified

### Created
- `chat/` (`__init__.py`, `apps.py`, `models.py`, `views.py`, `urls.py`, `agent.py`, `admin.py`, `tests.py`, `migrations/0001_initial.py`, `templates/chat/index.html`, `templates/registration/login.html`)
- `frontend/` (`package.json`, `vite.config.ts`, `tsconfig.json`, `src/chat.tsx`, `src/threadAdapter.ts`, `src/styles.css`)
- `doc/plans/2026-04-20-scott-rag-chatbot.md`
- `doc/features/2026-04-20-scott-rag-chatbot.md`
- `doc/sessions/2026-04-20-scott-rag-chatbot-planning-session.md`
- `doc/sessions/2026-04-20-scott-rag-chatbot-implementation-session.md`

### Modified
- `pyproject.toml` — `pydantic-ai[ag-ui]`, `django-vite`.
- `episodes/vector_store.py` — `search_chunks()`, `QdrantVectorStore.search()`, `ChunkSearchResult`.
- `ragtime/settings.py` — Scott settings, `django_vite` config, login URLs, `STATIC_ROOT`.
- `ragtime/urls.py` — include `chat.urls`, add `/accounts/login|logout/`.
- `ragtime/asgi.py` — path dispatcher mounting AG-UI behind auth middleware.
- `.env.sample` — Scott env var entries.
- `core/management/commands/_configure_helpers.py` — Scott subsystem.
- `core/tests/test_configure.py` — extend mock input streams for new prompts.
- `AGENTS.md` — Qdrant correction, Scott architecture section, frontend commands.
- `doc/README.md` — Scott section rewritten around the tool-call loop.
- `CHANGELOG.md` — 2026-04-20 entry.
