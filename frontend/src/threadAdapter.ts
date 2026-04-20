/**
 * Thread list + history adapters bridging assistant-ui to the Django
 * persistence endpoints in ``chat/views.py``.
 *
 * - `threadList` adapter: lists + creates conversations; on switch, loads
 *   their messages from Postgres.
 * - `history` adapter: persists every new message via `append(item)`;
 *   auto-creates a Django conversation on first append if none exists.
 *   `load()` restores messages on mount when the URL hash remembers the
 *   previously active thread id.
 *
 * We persist the active threadId to `localStorage` so a page refresh
 * can pick the conversation back up and replay its history.
 */

import type {
  ExportedMessageRepository,
  ExportedMessageRepositoryItem,
  ThreadMessage,
} from "@assistant-ui/react";

const ACTIVE_THREAD_STORAGE_KEY = "ragtime.scott.activeThreadId";

export function getCsrfToken(): string | null {
  const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : null;
}

async function jsonFetch<T>(
  url: string,
  init: RequestInit = {},
): Promise<T> {
  const headers = new Headers(init.headers ?? {});
  headers.set("Content-Type", "application/json");
  const csrf = getCsrfToken();
  if (csrf) headers.set("X-CSRFToken", csrf);
  const res = await fetch(url, {
    credentials: "same-origin",
    ...init,
    headers,
  });
  if (!res.ok) {
    throw new Error(`${init.method ?? "GET"} ${url} failed: ${res.status}`);
  }
  return (await res.json()) as T;
}

type ConversationDto = {
  id: number;
  title: string;
  created_at: string;
  updated_at: string;
};

type HistoryDto = {
  messages: ExportedMessageRepositoryItem[];
};

export type ThreadState = {
  threadId: string | null;
};

function rememberThreadId(id: string | null) {
  try {
    if (id) localStorage.setItem(ACTIVE_THREAD_STORAGE_KEY, id);
    else localStorage.removeItem(ACTIVE_THREAD_STORAGE_KEY);
  } catch {
    // localStorage may be unavailable (private browsing, disabled storage);
    // persistence within a single session still works via `state.threadId`.
  }
}

export function initialThreadState(): ThreadState {
  let stored: string | null = null;
  try {
    stored = localStorage.getItem(ACTIVE_THREAD_STORAGE_KEY);
  } catch {
    stored = null;
  }
  return { threadId: stored };
}

async function createConversation(): Promise<number> {
  const created = await jsonFetch<ConversationDto>(
    "/chat/api/conversations/",
    { method: "POST", body: JSON.stringify({}) },
  );
  return created.id;
}

export function buildThreadListAdapter(state: ThreadState) {
  return {
    get threadId() {
      return state.threadId;
    },
    async onSwitchToNewThread() {
      const id = await createConversation();
      state.threadId = String(id);
      rememberThreadId(state.threadId);
    },
    async onSwitchToThread(
      threadId: string,
    ): Promise<{ messages: readonly ThreadMessage[] }> {
      state.threadId = threadId;
      rememberThreadId(state.threadId);
      const history = await jsonFetch<HistoryDto>(
        `/chat/api/conversations/${encodeURIComponent(threadId)}/history/`,
      );
      return { messages: history.messages.map((item) => item.message) };
    },
  };
}

export function buildHistoryAdapter(state: ThreadState) {
  return {
    async load(): Promise<ExportedMessageRepository> {
      const threadId = state.threadId;
      if (!threadId) return { messages: [] };
      try {
        const history = await jsonFetch<HistoryDto>(
          `/chat/api/conversations/${encodeURIComponent(threadId)}/history/`,
        );
        return { messages: history.messages };
      } catch {
        // Thread may have been deleted server-side or belongs to another
        // user; forget it and start fresh instead of throwing.
        state.threadId = null;
        rememberThreadId(null);
        return { messages: [] };
      }
    },
    async append(item: ExportedMessageRepositoryItem): Promise<void> {
      if (!state.threadId) {
        // Auto-create a conversation on first append so a user who just
        // types a message (without clicking "new conversation") still
        // gets their turns persisted.
        const id = await createConversation();
        state.threadId = String(id);
        rememberThreadId(state.threadId);
      }
      await jsonFetch(
        `/chat/api/conversations/${encodeURIComponent(state.threadId)}/history/`,
        { method: "POST", body: JSON.stringify(item) },
      );
    },
  };
}
