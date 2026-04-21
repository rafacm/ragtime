# Conversation History UX — Planning Session

**Date:** 2026-04-21

**Session ID:** unavailable

## Summary

Planned the conversation history UX improvements for Scott. The user asked to implement point 1 from a PR follow-up comment — making saved conversations discoverable via a proper thread list backed by Django API endpoints. Explored the existing code, confirmed the PR review comment about undiscoverable conversations was covered by this work, and settled on `useRemoteThreadListRuntime` wrapping `useAgUiRuntime` via a `useScottRuntime` hook. The user gave feedback to use an LLM call for title generation instead of truncating the first user message. Plan was finalized with the LLM title generation approach.

## Detailed conversation

### User

> Implement point 1 of the PR #95 follow-up comment (conversation history UX). Check if it also covers the review comment about saved conversations not being discoverable.

### Assistant

Explored the PR comments on #95 to understand the follow-up items. Point 1 was about making the conversation history fully functional — the backend already persisted conversations and messages in Postgres, but the frontend used a localStorage-based adapter that never read them back. The thread list was always empty on page load.

Checked the review comment about discoverability — it flagged the same issue: conversations were saved server-side but the UI provided no way to browse them. Confirmed that implementing a proper `RemoteThreadListAdapter` backed by the existing Django API endpoints would address both the follow-up item and the review comment.

Analyzed the existing code: `frontend/src/threadAdapter.ts` had a localStorage-based implementation, `frontend/src/chat.tsx` used `useAgUiRuntime` directly without thread list support, and `chat/views.py` already had `api_conversations`, `api_conversation_detail`, and `api_conversation_history` endpoints ready to serve as the backend.

Proposed the approach: create a `RemoteThreadListAdapter` (from `@assistant-ui/core`) that maps `list`/`initialize`/`rename`/`delete` to the Django endpoints, build a `HistoryAdapter` using `useAui` from `@assistant-ui/store` for reactive access to the current thread's `remoteId`, and compose everything in a `useScottRuntime` hook using `useRemoteThreadListRuntime` wrapping `useAgUiRuntime`.

### User

> Does this cover the review comment about saved conversations not being discoverable?

### Assistant

Confirmed it does. The `RemoteThreadListAdapter.list()` calls `GET /chat/api/conversations/` which returns all conversations for the logged-in user. The sidebar renders this list, making every past conversation discoverable, clickable, and loadable. The review comment is fully addressed by this implementation.

### User

> Let's use an LLM call to create a better title instead of truncating the first user message.

### Assistant

Agreed — truncating the first user message produces titles like "What do you know about..." which are uninformative. Proposed a new `POST /chat/api/conversations/<id>/generate-title/` endpoint that accepts the first user message and assistant reply, uses a lightweight Pydantic AI Agent to generate a concise title (no quotes, max 6 words), saves it to the Conversation model, and returns it to the frontend. The frontend would call this after the first assistant reply completes and update the sidebar title in place. Cost is one cheap LLM call per new conversation. Plan was accepted with this approach.
