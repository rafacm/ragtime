# Scott: Implementation Plan

**Date:** 2026-04-20

## Context

Scott is the RAG chatbot described in `README.md` and `doc/README.md`: it answers questions strictly from ingested podcast content, responds in the user's language, cites specific episodes + timestamps, and streams responses. The infrastructure to power Scott is already in place (Qdrant vector store with citation-ready payloads, `Chunk` model with timestamps, OpenAI embedding provider, OpenTelemetry/Langfuse tracing) — what's missing is the chat app itself, a query-time retrieval helper, the agent, and a UI.

This plan covers the first production implementation of Scott. Decisions were made after reviewing the CopilotKit + Pydantic AI reference example at `github.com/CopilotKit/CopilotKit/tree/main/examples/integrations/pydantic-ai` and comparing alternatives.

## Current state (verified during exploration)

- **No `chat/` app exists.** `INSTALLED_APPS` is `['core', 'episodes']`. `ragtime/urls.py` only routes `admin/` and `episodes/`.
- **Vector store is Qdrant, not ChromaDB** (AGENTS.md is stale). `episodes/vector_store.py:QdrantVectorStore` has `ensure_collection`, `upsert_points`, `delete_by_episode` — **no search method yet**.
- Qdrant point payloads already carry citation-ready metadata: `chunk_id`, `episode_id`, `episode_title`, `episode_url`, `episode_published_at`, `episode_image_url`, `start_time`, `end_time`, `language`, `entity_ids`, `entity_names`, `text`.
- `Chunk` model (`episodes/models.py`) has `start_time`, `end_time`, `segment_start/end`, `index`, `text`, FK to `Episode`.
- Embedding: `text-embedding-3-small` (1536-dim, multilingual-capable). Factory at `episodes/providers/factory.py` driven by `RAGTIME_EMBEDDING_*`.
- `django.contrib.auth` is in `INSTALLED_APPS` and middleware, but no user-facing login flow exists — only the Django admin login. No `LOGIN_URL`, no `accounts/` routes.
- `ragtime/asgi.py` is the default Django ASGI shim — nothing mounted.
- Frontend today: pure Django templates + ~187 lines of vanilla JS (wikidata-search). No HTMX actually loaded, no Tailwind, no React, no build step.

## Chosen stack

| Area | Choice |
|---|---|
| Backend agent | Pydantic AI with `pydantic-ai-slim[ag-ui,openai]` |
| Agent hosting | AG-UI ASGI app mounted inside Django's ASGI stack at `/chat/agent/` (single Python process; no separate Starlette/Uvicorn service, no Next.js bridge) |
| Frontend | React island on `/chat/` using **assistant-ui** components + `@assistant-ui/react-ag-ui` (`useAgUiRuntime`) connecting directly to the AG-UI endpoint |
| Frontend build | Vite + `django-vite` (dev HMR + prod manifest/cache-busting). Tailwind 4 via `@tailwindcss/vite` |
| RAG shape | **Agentic tool-use** — `search_chunks` exposed as a Pydantic AI `@agent.tool`; system prompt mandates calling it before any factual answer and forbids general-knowledge fallbacks |
| Conversation history | **Persisted in Postgres** — new `Conversation` and `Message` models in the `chat` app; assistant-ui `threadList` + `history` adapters wired to Django endpoints |
| Auth | **Logged-in users** — `@login_required` on chat views; ASGI auth middleware on `/chat/agent/`; Django's built-in `LoginView` at `/accounts/login/`; admin-provisioned users |
| Scott LLM | OpenAI via new `RAGTIME_SCOTT_*` settings; Pydantic AI's `OpenAIResponsesModel` |
| Citation UX | Inline `[N]` markers in the streaming answer; source panel listing cited chunks with episode thumbnail, title, `MM:SS` timestamp, and deep link to the episode page |

This is the CopilotKit reference architecture with two substitutions that fit a Django shop: CopilotKit's Next.js runtime bridge is replaced by `@assistant-ui/react-ag-ui` (confirmed to exist on npm as version 0.0.26, backed by `@ag-ui/client`), and the standalone Python service is collapsed into Django's ASGI app.

### Rejected alternatives

- **Full CopilotKit + Next.js example as-is** — three processes in prod (Django, Next.js, Python agent) and auth/CORS bridging. Rejected; `@assistant-ui/react-ag-ui` gives the same UI goals with one fewer service.
- **HTMX + SSE, no React** — most Django-native, zero build step. Rejected because the user wants assistant-ui's component library.
- **Vanilla JS + hand-rolled AG-UI parsing** — skips the component library payoff of the build step. Rejected.
- **Classic one-shot RAG** — stricter by construction but the user opted for agentic tool-use for query refinement and multi-hop. Strictness is preserved via system prompt + tool-result-gated citation enforcement.

## Work to be done

### Backend — retrieval, agent, ASGI mount

1. **Deps.** Add `pydantic-ai-slim[ag-ui,openai]` and `django-vite` to `pyproject.toml`. `uv sync`.
2. **`episodes/vector_store.py`** — add `search_chunks(query, top_k=5, episode_id=None, score_threshold=None) -> list[ChunkSearchResult]`. Flow: fetch the configured `EmbeddingProvider`, embed the query, call the Qdrant client's `search()` on the existing collection with an optional `Filter(must=[FieldCondition(key="episode_id", match=MatchValue(value=...))])`. Return a dataclass with `chunk_id`, `episode_id`, `episode_title`, `episode_url`, `episode_image_url`, `start_time`, `end_time`, `language`, `text`, `score`.
3. **`chat/` app.** `manage.py startapp chat`. Register in `INSTALLED_APPS`.
4. **`chat/models.py`** —
   - `Conversation(user FK, title, created_at, updated_at)`.
   - `Message(conversation FK, role, content_json, tool_calls_json, created_at)` — rich enough to round-trip assistant-ui's `ThreadMessage` shape.
5. **`chat/agent.py`** — the Scott agent:
   - `ScottState(BaseModel)` carries the cumulative citation registry: `retrieved_chunks: list[ChunkSearchResult]` and `conversation_id: int | None`.
   - `agent = Agent(model=OpenAIResponsesModel(settings.RAGTIME_SCOTT_MODEL), deps_type=StateDeps[ScottState], system_prompt=SCOTT_SYSTEM_PROMPT)`.
   - Tool: `@agent.tool search_chunks(ctx, query, episode_id=None, top_k=5)` — delegates to the helper from step 2, dedupes by `chunk_id` against `ctx.deps.state.retrieved_chunks`, assigns 1-indexed `[N]` labels matching the cumulative position, emits a `StateSnapshotEvent` so the source panel updates live, returns a compact list the LLM can read (with `[N]` indices).
   - Expose via `agent.to_ag_ui(deps=StateDeps(ScottState()))` in a module-level `agui_app` ASGI callable.
6. **`chat/views.py`** — `chat_page` (renders the React shell, `@login_required`) + thread persistence endpoints for assistant-ui adapters: `list_conversations`, `create_conversation`, `get_conversation_messages`, `save_message`. All `@login_required`; JSON endpoints use Django's CSRF token (the React client includes it from the cookie).
7. **`chat/urls.py`** — page + persistence routes. Included in `ragtime/urls.py` under `chat/`.
8. **`ragtime/asgi.py`** — replace the default ASGI app with an ASGI dispatcher that:
   - Routes `/chat/agent/` → the Pydantic AI AG-UI app, wrapped in an auth middleware that validates the Django session cookie and rejects unauthenticated calls with 401.
   - Routes everything else → Django's normal ASGI app (`get_asgi_application()`).
9. **`ragtime/settings.py`** — add `RAGTIME_SCOTT_PROVIDER`, `RAGTIME_SCOTT_MODEL`, `RAGTIME_SCOTT_API_KEY`, `RAGTIME_SCOTT_TOP_K`, `RAGTIME_SCOTT_SCORE_THRESHOLD`; `LOGIN_URL = '/accounts/login/'`; `LOGIN_REDIRECT_URL = '/chat/'`; `django-vite` block (`DJANGO_VITE_ASSETS_PATH`, dev server port).
10. **Auth flow** — add Django's `auth_views.LoginView`/`LogoutView` at `/accounts/login/` and `/accounts/logout/` in `ragtime/urls.py`; add a minimal `registration/login.html` template. No self-signup in this iteration — accounts are created via Django admin.

### Frontend — React island via Vite + django-vite

11. **`frontend/` directory** at repo root: `package.json`, `vite.config.ts`, `tsconfig.json`, `postcss.config.mjs`, `src/chat.tsx`, `src/citations.tsx`, `src/threadAdapter.ts`.
12. **npm deps.** Runtime: `react`, `react-dom`, `@assistant-ui/react`, `@assistant-ui/react-ag-ui`, `@ag-ui/client`, `tailwindcss`, `@tailwindcss/vite`. Dev: `vite`, `@vitejs/plugin-react`, `typescript`, `@types/react`, `@types/react-dom`.
13. **`src/chat.tsx`** — entry point mounted into `#scott-root`. Creates `const agent = new HttpAgent({ url: "/chat/agent/", credentials: "same-origin" })`, passes it to `useAgUiRuntime({ agent, adapters: { history, threadList } })` from step 14, and wraps assistant-ui's `<Thread>` in `<AssistantRuntimeProvider runtime={runtime}>`.
14. **`src/threadAdapter.ts`** — implements `threadList` and `history` adapters that call the Django persistence endpoints from step 6. Sends the CSRF token from the cookie on mutating requests.
15. **`src/citations.tsx`** — custom message-part renderer that turns `[N]` inline markers in assistant text parts into clickable chips, plus a `<SourcePanel>` component that subscribes to `ScottState.retrieved_chunks` via the agent-state snapshot hook and renders one row per cited chunk (episode thumbnail, title, `MM:SS`, and a deep link like `/episodes/<id>/#t=<start_time>`).
16. **`chat/templates/chat/index.html`** — extends a minimal base template, loads `{% vite_hmr_client %}` and `{% vite_asset 'src/chat.tsx' %}`, renders the `#scott-root` mount point.

### Docs & config

17. Fix `AGENTS.md` — replace the ChromaDB reference with Qdrant; add a Scott architecture section.
18. Update `doc/README.md` Scott section with the agent tool-use loop, the `[N]` citation contract, and the Django + AG-UI ASGI topology.
19. Update `.env.sample` and `core/management/commands/configure.py` (wizard prompts for every new `RAGTIME_SCOTT_*` variable, matching the existing pattern).
20. Per CLAUDE.md workflow, the final commit includes:
    - `doc/plans/2026-04-20-scott-rag-chatbot.md` (this plan, after acceptance)
    - `doc/sessions/2026-04-20-scott-rag-chatbot-planning-session.md`
    - `doc/features/2026-04-20-scott-rag-chatbot.md` (written after implementation)
    - `doc/sessions/2026-04-20-scott-rag-chatbot-implementation-session.md`
    - `CHANGELOG.md` entry under `## 2026-04-20` → `### Added` with links to all four.

## System prompt outline

Draft (to be refined during implementation):

> You are Scott, a jazz podcast expert. You answer strictly from the transcripts provided by the `search_chunks` tool. **Before answering any factual question about podcasts, artists, bands, albums, venues, sessions, labels, or dates, you MUST call `search_chunks` at least once with a well-formed query.** You may call it multiple times with refined queries. If no relevant chunks are returned after reasonable search, say so plainly and stop — **never** answer from general knowledge. When citing, use `[N]` markers whose indices match the chunks shown in tool results. Reply in the user's language, regardless of the source episode's language.

A post-run validator will assert that every `[N]` emitted in the assistant message corresponds to an entry in `ScottState.retrieved_chunks`, catching drift even if the prompt is bypassed.

## Critical files

### Created
- `chat/` — `__init__.py`, `apps.py`, `models.py`, `views.py`, `urls.py`, `agent.py`, `admin.py`, `migrations/0001_initial.py`, `templates/chat/index.html`, `templates/registration/login.html`, `tests.py`.
- `frontend/` — `package.json`, `vite.config.ts`, `tsconfig.json`, `postcss.config.mjs`, `src/chat.tsx`, `src/citations.tsx`, `src/threadAdapter.ts`, `src/styles.css`.

### Modified
- `pyproject.toml` — add Pydantic AI + AG-UI + django-vite deps.
- `episodes/vector_store.py` — add `search_chunks()` + `ChunkSearchResult` dataclass.
- `ragtime/settings.py` — `INSTALLED_APPS` adds `chat` and `django_vite`; new `RAGTIME_SCOTT_*`, `LOGIN_URL`, `LOGIN_REDIRECT_URL`, `DJANGO_VITE_*` settings.
- `ragtime/urls.py` — include `chat.urls` and `accounts/` auth routes.
- `ragtime/asgi.py` — dispatcher mounting the AG-UI app behind auth middleware.
- `.env.sample` — new `RAGTIME_SCOTT_*` entries.
- `core/management/commands/configure.py` — wizard prompts for the new settings.
- `AGENTS.md` — fix Qdrant reference; add Scott section.
- `doc/README.md` — update Scott section.
- `CHANGELOG.md` — new dated entry with links to plan, feature doc, and session transcripts.

## Verification plan

1. **Unit — retrieval.** `search_chunks("Miles Davis Kind of Blue")` on a seeded Qdrant collection returns chunks ordered by cosine similarity with all expected payload fields. Episode-filtered variant honors the filter.
2. **Unit — refusal.** Seed Qdrant with two episodes; ask about a third. Run the agent with a mocked model; assert `search_chunks` was called, returned empty, and the final assistant message acknowledges no coverage.
3. **Unit — strict citation.** After every agent run, assert that every `[N]` index in the assistant message maps to an entry in `ScottState.retrieved_chunks`.
4. **Integration — streaming.** `uv run python manage.py runserver --noreload` (DBOS requires `--noreload`); log in; open `/chat/`; ask a question. Expect tokens streaming into the thread, live tool-call events, and the source panel populating as `search_chunks` runs.
5. **Manual — multilingual.** Ask "¿Qué opinan sobre Kind of Blue?" against an English-only corpus. Expect a Spanish answer with `[N]` citations pointing at English chunks.
6. **Manual — multi-hop follow-up.** Ask "¿Y su trompetista?" right after. Expect a second `search_chunks` call with a refined query and a cited follow-up answer.
7. **Manual — auth gate.** Logged out, GET `/chat/` → 302 to `/accounts/login/`. POST `/chat/agent/` with no session cookie → 401.
8. **Manual — persistence.** Start a conversation, hard-refresh, confirm assistant-ui's thread list shows it and clicking loads the full message history.
9. **Suite.** `uv run python manage.py test chat` passes.

## Out of scope (deferred)

- User self-signup / password reset / email verification.
- **Additional generative UI widgets** beyond the source panel. The source panel itself *is* generative UI (driven by `ScottState.retrieved_chunks` state snapshots). Not in scope for this iteration: inline audio player that autoplays the cited clip on `[N]` click; agent-suggested follow-up chips; human-in-the-loop confirmation prompts the agent can raise mid-answer (`useHumanInTheLoop`); timeline/map visualizations of entity mentions.
- **Multi-agent orchestration.** Scott is the only agent. Deferred: additional specialized agents (e.g., a pipeline-admin agent that could re-trigger ingestion from chat) routed behind the same chat UI.
- Rate limiting / per-user token budgets.
- Voice input / dictation (assistant-ui supports it via adapter).
- Offline evaluation harness for Scott's answers.
- A runtime switch for Scott's LLM provider beyond OpenAI (Pydantic AI makes this trivial to add later).
