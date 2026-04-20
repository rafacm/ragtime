/**
 * Thread list + history adapters bridging assistant-ui to the Django
 * persistence endpoints in ``chat/views.py``.
 *
 * - `threadList` adapter: lists + creates conversations; on switch, loads
 *   their messages from Postgres so refreshing the page restores the
 *   conversation.
 * - `history` adapter: persists every new message via `append(item)`; the
 *   `load()` fallback also lets assistant-ui reload on mount if a thread
 *   is already active.
 */

import type {
  ExportedMessageRepository,
  ExportedMessageRepositoryItem,
  ThreadMessage,
} from "@assistant-ui/react";

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

type ThreadListState = {
  threadId: string | null;
};

export function buildThreadListAdapter(state: ThreadListState) {
  return {
    get threadId() {
      return state.threadId;
    },
    async onSwitchToNewThread() {
      const created = await jsonFetch<ConversationDto>(
        "/chat/api/conversations/",
        { method: "POST", body: JSON.stringify({}) },
      );
      state.threadId = String(created.id);
    },
    async onSwitchToThread(
      threadId: string,
    ): Promise<{ messages: readonly ThreadMessage[] }> {
      state.threadId = threadId;
      const history = await jsonFetch<HistoryDto>(
        `/chat/api/conversations/${encodeURIComponent(threadId)}/history/`,
      );
      return { messages: history.messages.map((item) => item.message) };
    },
  };
}

export function buildHistoryAdapter(state: ThreadListState) {
  return {
    async load(): Promise<ExportedMessageRepository> {
      const threadId = state.threadId;
      if (!threadId) return { messages: [] };
      const history = await jsonFetch<HistoryDto>(
        `/chat/api/conversations/${encodeURIComponent(threadId)}/history/`,
      );
      return { messages: history.messages };
    },
    async append(item: ExportedMessageRepositoryItem): Promise<void> {
      const threadId = state.threadId;
      if (!threadId) return;
      await jsonFetch(
        `/chat/api/conversations/${encodeURIComponent(threadId)}/history/`,
        { method: "POST", body: JSON.stringify(item) },
      );
    },
  };
}
