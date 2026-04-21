import type {
  ExportedMessageRepository,
  ExportedMessageRepositoryItem,
  ThreadMessage,
} from "@assistant-ui/react";
import type {
  RemoteThreadListAdapter,
  RemoteThreadListResponse,
  RemoteThreadMetadata,
  RemoteThreadInitializeResponse,
} from "@assistant-ui/core";
import { createAssistantStream } from "assistant-stream";
import type { AssistantStream } from "assistant-stream";

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

function conversationUrl(id: string): string {
  return `/chat/api/conversations/${encodeURIComponent(id)}/`;
}

export function createDjangoThreadListAdapter(): RemoteThreadListAdapter {
  return {
    async list(): Promise<RemoteThreadListResponse> {
      const data = await jsonFetch<{ conversations: ConversationDto[] }>(
        "/chat/api/conversations/",
      );
      return {
        threads: data.conversations.map((c) => ({
          remoteId: String(c.id),
          status: "regular" as const,
          title: c.title || undefined,
        })),
      };
    },

    async initialize(): Promise<RemoteThreadInitializeResponse> {
      const created = await jsonFetch<ConversationDto>(
        "/chat/api/conversations/",
        { method: "POST", body: JSON.stringify({}) },
      );
      return { remoteId: String(created.id), externalId: undefined };
    },

    async rename(remoteId: string, newTitle: string): Promise<void> {
      await jsonFetch(conversationUrl(remoteId), {
        method: "PATCH",
        body: JSON.stringify({ title: newTitle }),
      });
    },

    async archive(): Promise<void> {},

    async unarchive(): Promise<void> {},

    async delete(remoteId: string): Promise<void> {
      await jsonFetch(conversationUrl(remoteId), { method: "DELETE" });
    },

    async fetch(threadId: string): Promise<RemoteThreadMetadata> {
      const c = await jsonFetch<ConversationDto>(conversationUrl(threadId));
      return {
        remoteId: String(c.id),
        status: "regular" as const,
        title: c.title || undefined,
      };
    },

    async generateTitle(
      remoteId: string,
      messages: readonly ThreadMessage[],
    ): Promise<AssistantStream> {
      const data = await jsonFetch<{ title: string }>(
        `${conversationUrl(remoteId)}generate-title/`,
        {
          method: "POST",
          body: JSON.stringify({
            messages: messages.map((m) => ({
              role: m.role,
              content: m.content,
            })),
          }),
        },
      );

      return createAssistantStream((controller) => {
        controller.appendText(data.title);
        controller.close();
      });
    },
  };
}

export function buildHistoryAdapter(
  getRemoteId: () => string | undefined,
  waitForRemoteId: () => Promise<string>,
) {
  return {
    async load(): Promise<ExportedMessageRepository> {
      const remoteId = getRemoteId();
      if (!remoteId) return { messages: [] };
      try {
        const data = await jsonFetch<HistoryDto>(
          `${conversationUrl(remoteId)}history/`,
        );
        return { messages: data.messages };
      } catch {
        return { messages: [] };
      }
    },

    async append(item: ExportedMessageRepositoryItem): Promise<void> {
      let remoteId = getRemoteId();
      if (!remoteId) {
        remoteId = await waitForRemoteId();
      }
      await jsonFetch(`${conversationUrl(remoteId)}history/`, {
        method: "POST",
        body: JSON.stringify(item),
      });
    },
  };
}
