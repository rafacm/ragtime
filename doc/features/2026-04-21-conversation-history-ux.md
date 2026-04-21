# Conversation History UX

**Date:** 2026-04-21

## Problem

Scott's chat UI stored thread state in localStorage via assistant-ui's default adapter. Conversations were persisted in Postgres by the Django backend, but the frontend never read them back — the thread list was always empty on page load. Users could not browse, rename, or delete past conversations. A PR review comment on the initial Scott implementation flagged that saved conversations were not discoverable.

Secondary issues: the dark theme was heavy for a reference tool, Scott's system prompt did not explicitly require translating chunk content into the user's language, and the `dbreset` command silently ran migrations.

## Changes

### Django-backed thread list

Replaced the localStorage-based thread adapter in `frontend/src/threadAdapter.ts` with a `RemoteThreadListAdapter` that maps to Django API endpoints. The adapter implements four methods (`list`, `initialize`, `rename`, `delete`) that call the existing `api_conversations` and `api_conversation_detail` views via `jsonFetch` with CSRF tokens.

Built a `HistoryAdapter` factory (`buildHistoryAdapter`) that uses `useAui` from `@assistant-ui/store` to reactively access the current thread's `remoteId`. The adapter's `load()` fetches `GET /chat/api/conversations/<id>/history/` and returns the `ExportedMessageRepository` shape; `append()` posts each new message to the same endpoint.

### useScottRuntime hook

Rewrote `frontend/src/chat.tsx` around a `useScottRuntime` custom hook that composes `useRemoteThreadListRuntime` (wrapping `useAgUiRuntime`). The hook wires the Django thread list adapter and history adapter together, creating a single runtime that manages thread switching, message streaming, and persistence.

The sidebar now renders a thread list with conversation titles, a delete button per thread, and a "New chat" button. Thread selection switches the active conversation and loads its history.

### LLM title generation

Added `POST /chat/api/conversations/<id>/generate-title/` — an async Django view that accepts the first user message and assistant reply, calls a Pydantic AI `Agent` with `output_type=str` to produce a concise title (no quotes, max 6 words), saves it to the `Conversation` model, and returns the title as JSON. The frontend calls this endpoint after the first assistant reply completes, then updates the sidebar title in place.

Error handling wraps the LLM call in a try/except so a failed title generation does not break the conversation flow — the conversation simply keeps its default title.

### Light theme and RAGtime banner

Replaced dark theme CSS variables in `frontend/src/styles.css` with light-theme values. Added an inline SVG logo with "RAGtime" wordmark to the sidebar header in `chat.tsx`.

### Cross-language system prompt rule

Added an explicit instruction to the Scott system prompt in `chat/agent.py`: when the user's language differs from the chunk's language, translate the relevant content into the user's language rather than quoting verbatim.

### dbreset cleanup

Removed the automatic `call_command("migrate")` from `core/management/commands/dbreset.py`. The command now prints explicit next steps after dropping and recreating the database: run `migrate`, `createsuperuser`, and `load_entity_types`.

### README updates

Added a telemetry section documenting OpenTelemetry, Langfuse, and Jaeger configuration. Updated dbreset instructions to reflect the removal of auto-migrate. Fixed the Jaeger Docker command. Added Scott to the "What's already implemented" list.

## Key parameters

| Parameter | Value | Rationale |
|---|---|---|
| Title generation max words | 6 | Keeps sidebar titles scannable without truncation |
| Title generation model | Same as `RAGTIME_SCOTT_MODEL` | Reuses existing config; no separate model setting needed |
| `output_type` on title agent | `str` | Simple string output, no structured extraction needed |

## Verification

1. Start a conversation, ask a question, wait for the response. The sidebar title should update to an LLM-generated title within seconds.
2. Hard-refresh the page. The sidebar should list all past conversations with their titles. Click one to reload its full message history.
3. Rename a conversation via the sidebar. Delete another. Both operations should persist across reloads.
4. Ask a question in French against English content. Scott should respond in French, translating chunk content.
5. The UI should render with a light background, dark text, and the RAGtime banner in the sidebar.
6. Run `uv run python manage.py dbreset` and verify it prints next steps without auto-migrating.

## Files modified

| File | Change |
|---|---|
| `frontend/src/threadAdapter.ts` | Rewritten: `RemoteThreadListAdapter` + `buildHistoryAdapter` replacing localStorage adapter. |
| `frontend/src/chat.tsx` | Rewritten: `useScottRuntime` hook, `useRemoteThreadListRuntime` composition, sidebar with thread list/delete/banner, light theme classes. |
| `frontend/src/styles.css` | Light theme CSS variables replacing dark defaults. |
| `frontend/package.json` | Added `@assistant-ui/core` and `@assistant-ui/store` dependencies. |
| `chat/views.py` | Added `api_generate_title` async view with Pydantic AI Agent for title generation, with error handling. |
| `chat/urls.py` | Added `generate-title/` URL pattern. |
| `chat/agent.py` | Updated system prompt with cross-language translation rule. |
| `core/management/commands/dbreset.py` | Removed auto-migrate; prints explicit next steps. |
| `README.md` | Added telemetry section, updated dbreset instructions, fixed Jaeger command, added Scott to implemented features. |
