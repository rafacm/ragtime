/**
 * Thread list adapter bridging assistant-ui's thread switcher to the
 * Django persistence endpoints in ``chat/views.py``.
 *
 * v1 scope:
 *   - list / create / delete conversations
 *   - switch to an empty fresh thread for an existing conversation
 *     (full message restoration across page refreshes is a v2 polish;
 *     the backend persists messages, the frontend does not yet replay them)
 */

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

export function buildThreadListAdapter() {
  return {
    threadId: null as string | null,
    async onSwitchToNewThread() {
      const created = await jsonFetch<ConversationDto>(
        "/chat/api/conversations/",
        { method: "POST", body: JSON.stringify({}) },
      );
      this.threadId = String(created.id);
    },
    async onSwitchToThread(threadId: string) {
      this.threadId = threadId;
      return { messages: [] as const };
    },
  };
}
