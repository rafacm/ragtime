# Conversation History UX: Implementation Plan

**Date:** 2026-04-21

## Context

Scott's initial implementation (2026-04-20) persisted conversations in Postgres (`Conversation` and `Message` models) and provided Django API endpoints for CRUD operations, but the frontend used a localStorage-based thread adapter. Saved conversations were not discoverable after a page reload — the thread list was empty and users had no way to browse, rename, or delete past conversations. A PR review comment flagged this gap explicitly.

Additionally, the dark theme felt heavy for a utility chat UI, the system prompt lacked explicit guidance on translating chunk content when the user's language differs from the source, and the `dbreset` management command ran migrations automatically, masking an important manual step.

## Approach

### Thread list and history

Replace the localStorage-based adapter with a `RemoteThreadListAdapter` (from `@assistant-ui/core`) backed by Django API endpoints. The adapter maps directly to existing Django views:

| Adapter method | Django endpoint |
|---|---|
| `list()` | `GET /chat/api/conversations/` |
| `initialize()` | `POST /chat/api/conversations/` |
| `rename()` | `PATCH /chat/api/conversations/<id>/` |
| `delete()` | `DELETE /chat/api/conversations/<id>/` |

For message history, build a `HistoryAdapter` that uses `useAui` from `@assistant-ui/store` to access the current thread's `remoteId`, then fetches and posts messages via `GET/POST /chat/api/conversations/<id>/history/`.

Compose everything in a `useScottRuntime` hook: `useRemoteThreadListRuntime` wrapping `useAgUiRuntime`, with the Django thread list adapter and history adapter wired in.

### LLM title generation

After the first assistant reply in a new conversation, the frontend calls `POST /chat/api/conversations/<id>/generate-title/` with the first user message and assistant reply. The Django view uses a lightweight Pydantic AI `Agent` to generate a concise conversational title (no quotes, max 6 words), then saves it to the `Conversation` model and returns it to the frontend, which updates the sidebar in place.

### Light theme and branding

Switch Tailwind/CSS from the assistant-ui dark defaults to a light theme. Add an inline SVG logo with "RAGtime" wordmark to the sidebar header, reinforcing the product identity.

### System prompt update

Add an explicit rule: when the user's language differs from the chunk language, Scott must translate the relevant content rather than quoting verbatim in the source language.

### dbreset cleanup

Remove the automatic `migrate` call from the `dbreset` management command. Print explicit next steps (`migrate`, `createsuperuser`, `load_entity_types`) so the user stays aware of what needs to happen after a reset.

## File changes

### Created
- None (all changes are to existing files).

### Modified
- `frontend/src/threadAdapter.ts` — Rewrite: `RemoteThreadListAdapter` + `buildHistoryAdapter` replacing localStorage adapter.
- `frontend/src/chat.tsx` — Rewrite: `useScottRuntime` hook composing `useRemoteThreadListRuntime` + `useAgUiRuntime`; sidebar with thread list, delete button, RAGtime banner; light theme classes.
- `frontend/src/styles.css` — Light theme CSS variables replacing dark defaults.
- `frontend/package.json` — Add `@assistant-ui/core` and `@assistant-ui/store` dependencies.
- `chat/views.py` — Add `api_generate_title` async view using Pydantic AI Agent.
- `chat/urls.py` — Add `generate-title/` URL pattern.
- `chat/agent.py` — Update system prompt with cross-language translation rule.
- `core/management/commands/dbreset.py` — Remove auto-migrate; print manual next steps.
- `README.md` — Add telemetry section, update dbreset instructions, fix Jaeger command, add Scott to "What's already implemented".

## Key design decisions

1. **`useRemoteThreadListRuntime` over custom state management** — assistant-ui provides this hook specifically for server-backed thread lists. It handles optimistic updates, loading states, and thread switching out of the box, avoiding hand-rolled state management.

2. **`useAui` for history adapter** — The history adapter needs the current thread's `remoteId` to fetch messages. `useAui` from `@assistant-ui/store` provides reactive access to the thread store outside of React component context, which is necessary since the adapter is a plain object, not a component.

3. **LLM-generated titles over truncation** — Truncating the first user message produces uninformative titles ("What do you know about..."). An LLM call produces concise, descriptive titles ("Miles Davis at Newport") that make the thread list scannable. The cost is one cheap LLM call per conversation.

4. **Light theme** — The dark theme was inherited from assistant-ui defaults. A light theme better matches the Django admin aesthetic and is easier to read for a reference/research tool.

## Verification

1. **Thread persistence round-trip.** Log in, start a conversation, ask a question. Hard-refresh the page. The sidebar should list the conversation with an LLM-generated title. Click it to reload the full message history.

2. **CRUD operations.** Create multiple conversations. Rename one via the sidebar. Delete one. Verify all operations persist across page reloads.

3. **Title generation.** Start a new conversation. After the first exchange, the sidebar title should update from "New conversation" to a concise LLM-generated title within a few seconds.

4. **Cross-language.** Ask a question in Spanish against English-only content. Verify Scott translates the relevant chunk content into Spanish rather than quoting English verbatim.

5. **Light theme.** Verify the chat UI renders with a light background, dark text, and the RAGtime SVG banner in the sidebar header.

6. **dbreset.** Run `uv run python manage.py dbreset`. Verify it does not auto-migrate and prints explicit next steps.
