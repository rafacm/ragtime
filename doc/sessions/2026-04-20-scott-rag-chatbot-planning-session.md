# Scott RAG Chatbot — Planning Session

**Date:** 2026-04-20

**Session ID:** unavailable

## Summary

Planned the first production implementation of **Scott**, RAGtime's strict-RAG jazz podcast chatbot. The conversation explored four candidate stacks (full CopilotKit + Next.js, assistant-ui + AG-UI, HTMX + SSE, vanilla JS + SSE), reviewed the CopilotKit/Pydantic AI reference example, and settled on a Django-native variant: a Pydantic AI agent exposed via AG-UI (HTTP+SSE) mounted inside Django's ASGI stack, with a React island built on assistant-ui + `@assistant-ui/react-ag-ui` for the frontend. Four locked decisions: agentic tool-use RAG, Postgres-persisted conversation history, login-required access, and inline `[N]` citation markers with a source panel. Rejected: CopilotKit's full Next.js stack (operational overhead), HTMX-only frontend (user wanted component library), and classic one-shot RAG (user preferred multi-hop query refinement, strictness preserved via system prompt + a citation integrity test).

## Detailed conversation

### User

> Let's focus on implementing Scott a conversational agent that answers questions strictly from ingested episode content. Scott responds in the user's language and provides references to specific episodes and timestamps. Responses stream in real-time. Help me brainstorm here. I am thinkin of using CopilotKit for the front-end and Pydantic AI for the backend agent logic.

### Assistant

Launched three parallel Explore agents to survey: (1) current state of the `chat/` Django app, (2) LLM/embedding/Qdrant plumbing available to reuse, (3) frontend stack and conventions already in the repo. Key findings:

- **No `chat/` app exists yet.** `INSTALLED_APPS` is just `['core', 'episodes']`; `ragtime/urls.py` only routes `admin/` and `episodes/`.
- **Vector store is Qdrant, not ChromaDB** — `AGENTS.md` is stale. `QdrantVectorStore` has `upsert_points`, `delete_by_episode`, `ensure_collection` but **no search method**. Point payloads already carry everything a citation needs: `chunk_id`, `episode_id`, `episode_title`, `episode_url`, `episode_image_url`, `start_time`, `end_time`, `language`, `entity_ids`, `entity_names`, `text`.
- **Embedding** uses `text-embedding-3-small` (1536-dim, multilingual-capable) via `episodes/providers/factory.py`.
- **`LLMProvider`** has `generate()` and `structured_extract()`, no streaming. OpenAI is the only concrete implementation.
- **Frontend** is pure Django templates + ~187 lines of vanilla JS (wikidata-search). No HTMX actually loaded, no Tailwind, no React, no build step. `AGENTS.md`'s "HTMX + Tailwind CDN" is aspirational.

Wrote an initial brainstorm doc capturing current state and three candidate stacks (CopilotKit, HTMX+SSE, vanilla JS+SSE), plus observations on Pydantic AI fit. Presented tradeoffs and asked four clarifying questions (frontend stack, RAG shape, history, auth). User asked to clarify questions before answering.

### User

> What is the usual approach to introduce a React, TailwindCSS and other front-end technologies in a Django app?

### Assistant

Explained the three common patterns from lightest to heaviest: (1) Django-rendered HTML + Tailwind standalone CLI (no Node in prod); (2) Django + React "islands" via `django-vite` (Vite for the build, Tailwind integrated, `{% vite_asset %}` template tags, two dev processes — the usual answer for a case like this); (3) fully decoupled Django API + separate SPA. Noted that CopilotKit specifically slots into pattern #2 or #3 and requires a Node runtime sidecar or reimplementing its protocol. Mentioned HTMX+Alpine+Tailwind as the "server-rendered alternative" with no build step.

### User

> There is an example here on how to integrate CopilotKit and PydanticAI

### Assistant

Asked for the link.

### User

> https://github.com/CopilotKit/CopilotKit/tree/main/examples/integrations/pydantic-ai

### Assistant

Fetched the example via `gh api`. Read the README, `package.json`, `agent/pyproject.toml`, `agent/src/main.py`, `agent/src/agent.py`, `src/app/page.tsx`, `src/app/layout.tsx`, and `src/app/api/copilotkit/route.ts`. Found:

- **Python agent:** Starlette+Uvicorn on :8000, `pydantic-ai-slim[ag-ui]`, `agent.to_ag_ui(deps=StateDeps(ProverbsState()))` — turns a Pydantic AI `Agent` into an ASGI app speaking the **AG-UI protocol** (HTTP+SSE, not CopilotKit-specific). Tools via `@agent.tool`. State is a Pydantic model.
- **Next.js frontend:** React 19, Tailwind 4, `@copilotkit/react-core`, `@copilotkit/react-ui`, `<CopilotSidebar>`, hooks `useCoAgent`, `useRenderToolCall`, `useFrontendTool`, `useHumanInTheLoop`.
- **Next.js API route** (`src/app/api/copilotkit/route.ts`): TypeScript bridge using `CopilotRuntime` + `HttpAgent`. The glue; CopilotKit does not publish a Django equivalent.

Wrote up the implications: the integration is Next.js-shaped. Listed three adaptation paths for Django: (A) full CopilotKit stack as a separate Next.js service side-by-side with Django (most faithful, heaviest); (A') Django-hosted Pydantic AI agent + React island, talking directly to AG-UI — skipping the CopilotKit runtime bridge (lighter, loses some CopilotKit UI sugar); (iii) mount the Pydantic AI AG-UI ASGI app inside Django's ASGI stack — cleanest Python side. Updated the brainstorm doc.

### User

> Are there alternatives to CopilotKit that would integrate with Django?

### Assistant

Listed six alternatives grouped by Django-fit:

1. **Vercel AI SDK + `@ai-sdk/react`** — backend-agnostic React chat hooks + components (NDJSON Data Stream Protocol over SSE); good fit with Django because any streaming endpoint works; pairs naturally with Pydantic AI.
2. **assistant-ui** — React component library with runtime adapters; same backend-agnostic shape as #1 with a more polished component set.
3. **Pydantic AI via AG-UI, no CopilotKit** — mount `agent.to_ag_ui()` in Django ASGI; consume from a React island with `@ag-ui/client` directly.
4. **django-ai-assistant** — Django-native but LangChain-based; would fight against Pydantic AI choice.
5. **Chainlit** — Python-first but standalone; iframe-level Django integration only.
6. **HTMX + SSE** — zero new tech, matches project direction.

Ranked for this project: Vercel AI SDK > HTMX+SSE > AG-UI + assistant-ui > full CopilotKit.

### User

> For option 3, can we also use django-vite or we do not need it?

### Assistant

Explained: if the frontend uses React + npm packages (assistant-ui, `@ag-ui/client`), some bundler is required — Vite is the standard; `django-vite` is optional but recommended (adds dev HMR and prod manifest handling; without it, `vite build` output just goes into `STATIC_ROOT` with hardcoded paths). If the frontend stays vanilla JS talking straight to AG-UI's HTTP+SSE, no Vite needed. No middle ground where you get React components without a bundler.

### User

> I want to use assistant-ui because I want to re-use all the UI components that it offers.

### Assistant

Verified the integration path by inspecting `github.com/assistant-ui/assistant-ui` via `gh api`. Confirmed that `@assistant-ui/react-ag-ui` exists (version 0.0.26, backed by `@ag-ui/client`) and exposes `useAgUiRuntime` — a hook that plugs assistant-ui components directly into an AG-UI endpoint. This means Pydantic AI's `to_ag_ui()` output can feed assistant-ui components with no CopilotKit runtime bridge and no Next.js. Rewrote the "Candidate stacks" section of the plan to lock in Django-hosted Pydantic AI agent + React island via Vite+`django-vite`+assistant-ui+`@assistant-ui/react-ag-ui`.

Asked four focused questions on the remaining decisions: RAG shape (classic vs agentic vs hybrid), conversation history (Postgres vs session vs stateless), auth (public vs logged-in vs staff-only), citation UX (inline markers + source panel vs per-citation cards vs tooltips).

### User

Selected: **agentic tool-use**, **persisted in Postgres**, **logged-in users**, **inline markers + source panel**.

### Assistant

Noted that agentic tool-use weakens the "strict from ingested content" guarantee unless the system prompt is disciplined — decided to preserve strictness via a strong system prompt ("MUST call `search_chunks` before any factual answer", "never answer from general knowledge") plus a unit-test-backed citation integrity check (every `[N]` in the assistant message must map to `ScottState.retrieved_chunks`).

Verified the auth landscape: `django.contrib.auth` is already enabled with middleware; no `LOGIN_URL`, no `accounts/` routes yet. Planned to add Django's built-in `LoginView`/`LogoutView` with a minimal `registration/login.html` template; accounts provisioned via admin — no self-signup in this iteration.

Did a full rewrite of the plan file to clean up accumulated cruft from earlier iterations and lock everything in: chosen stack table, detailed work breakdown (backend → frontend → docs), system prompt outline, critical files (created / modified), verification plan (9 items), out-of-scope list. Called `ExitPlanMode`.

### User

> What does this mean "Multi-agent or non-Scott generative UI beyond the source panel"?

### Assistant

Unpacked the jargon: **multi-agent** = CopilotKit pattern of multiple specialized agents behind one chat UI (we're not doing this — Scott is the only agent). **Generative UI** = the AG-UI / CopilotKit / assistant-ui concept of the agent driving rich React components via tool calls or state snapshots (`useRenderToolCall`, `useHumanInTheLoop`). The source panel we *are* building is generative UI — driven by `ScottState.retrieved_chunks` state snapshots. The "out of scope" line was saying we defer *other* generative UI ideas like audio player autoplay on `[N]` click, agent-suggested follow-up chips, human-in-the-loop confirmation prompts, timeline/map visualizations. Rewrote that "Out of scope" bullet to be more concrete, then called `ExitPlanMode` again. User approved.
