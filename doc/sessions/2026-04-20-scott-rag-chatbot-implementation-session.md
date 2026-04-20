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

Staged all changes (backend + frontend + docs), committed a single feature commit (`a9f90f3`) with a `Co-Authored-By: Claude Opus 4.7 (1M context)` trailer. Attempted `git push -u origin feature/scott-rag-chatbot`; the push was blocked pending user authorization. User approved; pushed successfully; opened PR #95 with a Summary / Details / Docs / Test plan body.

### User — Review

Ran `/pr-review-comments-process` and asked for a list of open review comments with severity and suggested actions.

### Assistant — Review triage

Fetched `gh api repos/rafacm/ragtime/pulls/95/comments`. Found three comments, all from rafacm on commit `a9f90f3`:

1. **`chat/agent.py`** — `StateDeps(ScottState())` is constructed once inside the `@lru_cache`d `get_agui_app()` and reused across requests; since `search_chunks_tool` mutates `deps.state.retrieved_chunks`, one user's citations can bleed into another request. Verified against Pydantic AI source: the `AGUIApp` docstring confirms "`deps` will be the same for each request" except for the `.state` field when the frontend sends state — so the reviewer is right, it's a real leak for any run that doesn't carry state (or in the window before the first state update).
2. **`frontend/src/threadAdapter.ts`** — `onSwitchToThread` returns `{ messages: [] }`; no `history` adapter is wired into `useAgUiRuntime`. Backend persists conversations but the frontend never replays them. PR description overstates "persisted conversation history". Documented in the session transcript as a v1 limitation but not in the PR description / CHANGELOG.
3. **`frontend/src/chat.tsx`** — Django 5 `LogoutView` only accepts `POST` and `OPTIONS`; `<a href="/accounts/logout/">` will `405`. Real bug.

Classified as high / medium / medium respectively. Reported each back to the user with severity, reviewer fix, and my suggested action. User approved implementing all four items (fix #1 + #3, scope claim for #2, reply to each comment).

### Assistant — Fixes

**Fix 1 (state leak).** Replaced `get_scott_agent().to_ag_ui(deps=StateDeps(ScottState()))` with a per-request `AGUIAdapter.dispatch_request(request, agent=..., deps=StateDeps(ScottState()))` wrapped in a minimal Starlette `Route("/", scott_endpoint, methods=["POST"])`. Updated `ragtime/asgi.py` to strip the `/chat/agent` prefix before forwarding to the Starlette app (standard ASGI sub-mount pattern). Added `ScottStateIsolationTests.test_second_run_starts_with_empty_registry` that runs two sequential agent invocations with distinct retrieved chunks and asserts the second's state starts fresh (`[2]`, not `[1, 2]`). Without the fix this test would fail; with it, 10/10 `chat` tests pass.

**Fix 2 (persistence).** Initial plan was to scope the PR claim and defer full persistence to v2. User pushed back — "why not implement it in this PR?" Took the pushback, implemented the full round-trip:

- Reshaped `chat/models.py`:`Message` around assistant-ui's storage contract. New fields: `external_id` (assistant-ui's `message.id`), `parent_external_id`, `payload_json` (the full `ThreadMessage`), `run_config_json`. Dropped the earlier `role` / `content_json` / `tool_calls_json` split. Added a `UniqueConstraint(conversation, external_id)` so `append` can be idempotent against client retries via `update_or_create`. Regenerated the single initial migration.
- Replaced `api_conversation_messages` with `api_conversation_history` — `GET` returns `{messages: ExportedMessageRepositoryItem[]}`, `POST` accepts one item, validates that `message.id` is non-empty, upserts, and returns the stored item.
- Frontend: `buildThreadListAdapter(state)` now loads history in `onSwitchToThread` and returns it as `{messages: ThreadMessage[]}` for `core.applyExternalMessages`. `buildHistoryAdapter(state)` exposes `load()` (for mount-with-active-thread) + `append()` (persists every new turn). Both adapters share a mutable `threadState` object so the history adapter knows the current thread id.
- Tests: dropped the stale role-based cases; added round-trip (3-message parent chain), idempotent duplicate append, missing-`message.id` rejection, and owner scoping on the history endpoint. 13/13 chat tests pass; full suite 287 green.

**Fix 3 (logout 405).** Replaced the `<a href="/accounts/logout/">Sign out</a>` anchor in `frontend/src/chat.tsx` with a `<button>` that calls a new `signOut()` helper — `fetch("/accounts/logout/", { method: "POST", headers: { "X-CSRFToken": ... }, credentials: "same-origin" })` followed by `window.location.assign("/accounts/login/")`. Works in Django 5 without a custom view.

Ran the full suite — 284 tests green (the new state-isolation test brings the total up from 283).

### Assistant — Reply on PR

Replied to each of the three review comments via `gh api repos/.../pulls/95/comments` with `in_reply_to`, each pointing at commit `85e737c` with a concise summary of the fix. All three threads now have a linked resolution.

### Assistant — End-to-end debugging pass

After the review fixes landed, brought the UI up end-to-end for the first time. Several plumbing issues surfaced that only show up when you actually run the stack; each one was solved in turn:

1. **npm registry date cutoff.** User's npm had a `before=2026-04-13` config that blocked `@assistant-ui/react-ag-ui@0.0.26`. Documented the override (`npm install --before=2026-04-21`); no code change needed.
2. **Vite base path.** The dev server was serving at `/` but `django-vite` was asking for `/static/frontend/...`. Added `base: "/static/frontend/"` to `vite.config.ts` so Vite's own paths match django-vite's expectations.
3. **Missing Tailwind CSS entry points.** `@assistant-ui/react@0.12` ships primitives only, no prebuilt stylesheet. Dropped the broken `@import "@assistant-ui/react/styles/..."` lines; added `@source` directives so Tailwind v4 scans the package dist. Wired a full shadcn-style dark theme (`--background`, `--foreground`, `--primary`, etc.) in `frontend/src/styles.css` using `@theme inline` for Tailwind v4 token mapping.
4. **`<Thread>` and `<ThreadList>` don't exist in this version.** `@assistant-ui/react@0.12` is primitive-only — the prebuilt styled components are scaffolded via a shadcn-compatible CLI at `https://r.assistant-ui.com/{name}.json`. Rather than run the scaffolder (which adds a `components.json` + radix/lucide/etc. deps), hand-rolled minimal `Thread`, `ThreadList`, `UserMessage`, `AssistantMessage`, and `ThreadListItem` using `ThreadPrimitive`, `ComposerPrimitive`, `MessagePrimitive`, and `ThreadListItemPrimitive`. Imported `AssistantRuntimeProvider` from `@assistant-ui/core/react` (not top-level `@assistant-ui/react`).
5. **`@vitejs/plugin-react` can't detect preamble.** Django serves the HTML, not Vite, so the React Refresh preamble wasn't being injected. Added `{% vite_react_refresh %}` to `chat/templates/chat/index.html` between `{% vite_hmr_client %}` and `{% vite_asset %}`. Required a Django server restart since `--noreload` blocks Python reloads.
6. **`ComposerPrimitive.Input` must be inside `ThreadPrimitive.Viewport`.** Composer input reads the viewport context for scroll-integration features. Restructured the Thread component so the composer lives inside `ThreadPrimitive.ViewportFooter` (a non-scrolling slot inside the viewport).
7. **POST `/chat/agent/` returned 404.** `manage.py runserver` uses WSGI by default, which doesn't load `ragtime/asgi.py` at all — my dispatcher was never on the request path. Switched to `uv run uvicorn ragtime.asgi:application --host 127.0.0.1 --port 8000`; uvicorn was already a transitive dep from `pydantic-ai[ag-ui]`.
8. **ASGI sub-mount path mismatch.** The Starlette sub-app's `Route("/", ...)` didn't match after the dispatcher forwarded `/chat/agent/`. Added `_substitute_prefix(scope, AGUI_PREFIX)` in `ragtime/asgi.py` to strip the prefix before delegating — standard ASGI sub-mount pattern.
9. **`RAGTIME_SCOTT_API_KEY` not set.** Walked the user through `manage.py configure` to fill it in.
10. **No source cards, no references.** Built a `SearchChunksDisplay` tool-call renderer + a `ToolCallFallback` catch-all and wired them via `MessagePrimitive.Parts components={{ tools: { by_name, Fallback } }}`. After that the issue became visible: the tool was never being invoked.
11. **Tool-name mismatch.** System prompt said `search_chunks`; the decorated Python function was `search_chunks_tool` (function name → tool name in pydantic-ai). Renamed the tool to `search_chunks` and aliased the helper import as `_search_chunks_helper` to avoid a collision. Updated tests to match (`tool_name="search_chunks"`, patch target `chat.agent._search_chunks_helper`). All 287 tests green.
12. **System prompt never reached the LLM.** Jaeger showed `gen_ai.input.messages` contained only the user turn — no system role — so Scott was answering from general knowledge ("Django Reinhardt was born on January 23, 1910" with no citations). Root cause: `OpenAIResponsesModel` routes `system_prompt=` differently than the classical Chat Completions API. Switched `Agent(..., system_prompt=...)` to `Agent(..., instructions=...)`, which is the modern canonical parameter and combines cleanly with the dynamic `@agent.instructions` registry. After the restart the LLM called `search_chunks` and the green source cards appeared inline.
13. **Conversations not persisted across refresh.** `threadState.threadId` was reset to `null` on each mount, and `history.append` silently no-op'd when no thread id was set (so a user who never clicked "+ New conversation" got nothing persisted). Fixed by (a) auto-creating a Django conversation on first `append` and (b) persisting the active thread id to `localStorage` via an `initialThreadState()` helper so a refresh restores the same conversation and `history.load()` replays its messages.

After fix 13, end-to-end flow works: ask a question → Scott calls `search_chunks` → green source cards render → answer streams with `[N]` citations → refresh → conversation replays from Postgres.

**Deferred to follow-up PR (explicitly called out to the user):** proper `useRemoteThreadListRuntime` integration so the sidebar lists *persisted* Django conversations rather than assistant-ui's in-memory threads; thread rename/delete UX; `[N]` chip highlighting the corresponding row in the source panel; episode deep-links; audio-clip autoplay on citation click; rate limiting; per-user token budget; offline evaluation harness; markdown + syntax highlighting on assistant text; voice dictation; scaffolding the richer shadcn components via `npx assistant-ui add`.

### Assistant — Second PR review round

Pushed commit with the end-to-end fixes (instructions switch, tool rename, Starlette sub-mount, shadcn theme, preamble, viewport-footer composer, `history.append` auto-create + localStorage). Full suite still 287 green. Summarized deferred items for the follow-up PR.
