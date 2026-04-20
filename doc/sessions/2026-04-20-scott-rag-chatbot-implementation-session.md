# Scott RAG Chatbot — Implementation Session

**Date:** 2026-04-20

**Session ID:** unavailable

## Summary

Implemented the plan agreed in the planning session. Built the `search_chunks` retrieval helper on top of the existing `QdrantVectorStore`, scaffolded the `chat/` Django app with `Conversation` / `Message` models, created the Scott Pydantic AI agent with a strict-RAG system prompt and a `search_chunks_tool`, mounted the AG-UI ASGI app inside Django's ASGI stack behind a session-cookie auth middleware, added `LoginView`-based auth routes with a minimal template, scaffolded the `frontend/` Vite + React + Tailwind + assistant-ui island with a `threadList` adapter talking to the Django persistence endpoints, updated `.env.sample` / the configure wizard / `AGENTS.md` / `doc/README.md`, and added a test suite that covers retrieval, agent refusal on empty retrieval, citation integrity, auth gating, and full conversation CRUD. All 283 tests pass.

## Detailed conversation

### User

> Let's focus on implementing Scott a conversational agent that answers questions strictly from ingested episode content. […]

(See planning session transcript.)

### Assistant — Setup

Verified `main` branch, pulled (already up to date), created a git worktree `feature/scott-rag-chatbot` per the user's feedback memory. Inspected `pyproject.toml`: `pydantic-ai>=1.30,<2` was already a dependency (the meta-package), but `ag-ui` was not — replaced with `pydantic-ai[ag-ui]>=1.30,<2`, added `django-vite>=3.0,<4`, ran `uv sync`. Verified `from pydantic_ai.ag_ui import StateDeps` imports cleanly.

Created 19 tracking tasks via TaskCreate spanning backend retrieval, agent, ASGI mount, settings, auth, frontend scaffold, React chat island, template, tests, env/wizard, docs, and PR.

### Assistant — Retrieval

Edited `episodes/vector_store.py` to add `ChunkSearchResult` (frozen dataclass with citation-ready fields) and a `QdrantVectorStore.search(query_vector, top_k, episode_id=None, score_threshold=None)` method using `client.query_points`. Added a module-level `search_chunks(query, …)` function that embeds the query via `get_embedding_provider()` and calls `get_vector_store().search(...)`. Verified imports.

### Assistant — Chat app scaffold

`manage.py startapp chat`. Hit a startup error: `django_vite` raised `TypeError: argument should be a str or an os.PathLike object` because `STATIC_ROOT` was unset. Brought the settings work forward: added `STATIC_ROOT`, `STATICFILES_DIRS` pointing at `frontend/dist`, `LOGIN_URL`, `LOGIN_REDIRECT_URL`, a `DJANGO_VITE` block, and all five `RAGTIME_SCOTT_*` settings. Re-ran `makemigrations chat` — green. Migration created `Conversation` and `Message` models with correct FK + JSON fields.

### Assistant — Scott agent

Wrote `chat/agent.py` with a lazily-built agent (`@lru_cache` on `get_scott_agent()` and `get_agui_app()`) so Django can boot without the OpenAI API key set. Followed the pattern from `episodes/agents/agent.py:_build_model` — passes `api_key` explicitly via `OpenAIProvider`, avoiding env-var mutation.

Initial attempt made the `search_chunks_tool` return a `StateSnapshotEvent` directly (as the CopilotKit example does). Switched to returning a compact list of indexed chunks for the LLM's tool-result view, while mutating `ctx.deps.state.retrieved_chunks` for the AG-UI state snapshot (Pydantic AI's `StateDeps` auto-emits state snapshots on mutation). Added a dynamic `@agent.instructions` callable that injects the cumulative citation registry into every turn — guarantees the LLM always sees `[N]` labels even when the tool result alone is not in context window.

Verified the module loads without credentials.

### Assistant — ASGI mount

Rewrote `ragtime/asgi.py` as a path-based dispatcher. `/chat/agent/` is wrapped in an auth middleware that parses the `Cookie` header, loads the Django session store via `SessionStore(session_key=...)`, validates `user_id` + `backend_path`, fetches the user asynchronously, and checks `user.is_active`. Unauthenticated calls get a 401 JSON response. Everything else falls through to Django's standard ASGI app. Verified the callable constructs cleanly.

### Assistant — Views, URLs, auth

`chat/views.py`: `chat_page` (login_required) + JSON `api_conversations`, `api_conversation_detail`, `api_conversation_messages`. All scoped to `request.user`, all `@require_http_methods` guarded, pass opaque JSON payloads through.

`chat/urls.py` (namespaced `chat`) + `ragtime/urls.py` updated to include `chat/` and `accounts/login|logout/` using `django.contrib.auth.views`. Added a standalone `registration/login.html` template (dark palette, standard POST form, `next=/chat/` hidden input).

### Assistant — Frontend

Created `frontend/` with `package.json` (React 19, assistant-ui 0.12, `@assistant-ui/react-ag-ui` 0.0.26, `@ag-ui/client` 0.0.52, Tailwind 4 via `@tailwindcss/vite`), `vite.config.ts` (manifest build, rollup input at `src/chat.tsx`, strict port 5173), `tsconfig.json`.

`src/chat.tsx`: `HttpAgent` with CSRF header, `useAgUiRuntime` with `threadList` adapter and `showThinking: true`, renders assistant-ui's `<Thread>` + `<ThreadList>` in a two-column layout with a logout link in the sidebar footer.

`src/threadAdapter.ts`: minimal `threadList` adapter — lists, creates, and switches conversations via the Django endpoints. **v1 limitation documented:** `onSwitchToThread` returns an empty messages array. Full history replay is deferred to v2 — backend already persists messages, frontend adapter just doesn't decode them yet.

`src/styles.css`: imports Tailwind + assistant-ui stylesheets + a minimal dark palette on html/body/#scott-root.

`chat/templates/chat/index.html`: Django shell using `{% vite_hmr_client %}` and `{% vite_asset 'src/chat.tsx' %}` with a `#scott-root` mount point.

### Assistant — Tests

Wrote `chat/tests.py` with five test classes:

- `SearchChunksTests` — patch `get_vector_store` and `get_embedding_provider` with fakes, assert `search_chunks` passes top_k / episode_id / score_threshold through to the store and returns the store's results.
- `ScottAgentBehaviorTests` — uses `override_settings(RAGTIME_SCOTT_API_KEY="sk-test-placeholder")` and Pydantic AI's `FunctionModel` with a scripted response list to deterministically test: (a) refusal path when `search_chunks` returns empty, (b) citation integrity — every `[N]` in the assistant message maps to `ScottState.retrieved_chunks`. Clears the `get_scott_agent` lru_cache between tests so each gets a fresh agent with its own override.
- `ChatAPITests` — auth gating (`/chat/` redirects to login; `/chat/agent/` returns 401 when called via the ASGI callable directly with an empty cookie), full conversation CRUD, owner scoping, invalid-role rejection.
- `ChunkSearchResultShapeTests` — regression check that `asdict(ChunkSearchResult)` contains every field the agent state round-trips.

Initial run had three failures:
1. `Agent()` constructor tried to build an `AsyncOpenAI` client and threw `OpenAIError: api key must be set`. Fixed by adding `@override_settings(RAGTIME_SCOTT_API_KEY="sk-test-placeholder")` at the class level.
2. `test_agent_endpoint_rejects_anonymous` failed because Django's sync test client doesn't exercise the ASGI dispatcher. Rewrote to invoke `ragtime.asgi.application(scope, receive, send)` directly with `asyncio.run` and inspect the synthetic response.
3. After that, the full suite surfaced three `StopIteration` errors in `core.tests.test_configure.ConfigureWizardTest` — the mock input streams ran out because my Scott subsystem added new wizard prompts. Extended the three affected test methods with the new Scott entries (1 secret via getpass, 4 non-secret via input).

Final result: `uv run python manage.py test` — **283 tests, 0 failures**.

### Assistant — Env & wizard

`.env.sample`: added a Scott block under the Embedding section with commented descriptions for all five `RAGTIME_SCOTT_*` vars. `core/management/commands/_configure_helpers.py`: added a `Scott (RAG chatbot)` subsystem after Qdrant with the same pattern as Recovery.

### Assistant — Docs

`AGENTS.md`: replaced the ChromaDB reference with Qdrant, rewrote the Scott section to describe the Pydantic AI + AG-UI + assistant-ui topology, added frontend `npm` commands to the Commands section.

`doc/README.md`: rewrote "How Scott Works" around the tool-call loop, added a configuration table for the five new settings, and added an ASCII topology diagram showing the ASGI dispatch.

Copied the plan to `doc/plans/2026-04-20-scott-rag-chatbot.md` and added the `**Date:** 2026-04-20` metadata line. Wrote `doc/features/2026-04-20-scott-rag-chatbot.md` with Problem / Changes / Key parameters / Verification / Files modified sections. Wrote both session transcripts.

### Assistant — Verification

Ran the full test suite twice (after fixing the wizard mocks, final run green). Did not run the interactive smoke test end-to-end (requires a real OpenAI key, a logged-in session, the Vite dev server, and Qdrant with ingested episodes) — documented the expected flow in the feature doc's Verification section and the plan's Verification plan. Noted the `staticfiles.W004` warning about `frontend/dist` — expected while the Vite build hasn't been run; disappears after `npm run build`.

### Assistant — Commit + PR

(To be appended during the commit + PR step.)
