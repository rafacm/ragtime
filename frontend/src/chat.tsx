import "./styles.css";

import { HttpAgent } from "@ag-ui/client";
import {
  ComposerPrimitive,
  MessagePrimitive,
  ThreadPrimitive,
  ThreadListItemPrimitive,
  ThreadListPrimitive,
} from "@assistant-ui/react";
import { AssistantRuntimeProvider } from "@assistant-ui/core/react";
import { useAgUiRuntime } from "@assistant-ui/react-ag-ui";
import { useCallback, useMemo } from "react";
import { createRoot } from "react-dom/client";

import {
  buildHistoryAdapter,
  buildThreadListAdapter,
  getCsrfToken,
  initialThreadState,
} from "./threadAdapter";

async function signOut() {
  await fetch("/accounts/logout/", {
    method: "POST",
    credentials: "same-origin",
    headers: { "X-CSRFToken": getCsrfToken() ?? "" },
  });
  window.location.assign("/accounts/login/");
}

function UserMessage() {
  return (
    <MessagePrimitive.Root className="flex justify-end px-4 py-2">
      <div className="rounded-2xl bg-primary text-primary-foreground px-4 py-2 max-w-[80%]">
        <MessagePrimitive.Parts />
      </div>
    </MessagePrimitive.Root>
  );
}

type RetrievedChunk = {
  citation: string;
  episode_title: string;
  start_time: number;
  end_time: number;
  language: string;
  score: number;
  text: string;
};

type SearchChunksArgs = {
  query?: string;
  episode_id?: number | null;
  top_k?: number | null;
};

function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

function SearchChunksDisplay(props: {
  args: SearchChunksArgs;
  result?: RetrievedChunk[];
  status?: { type: string };
}) {
  const { args, result } = props;
  const chunks = Array.isArray(result) ? result : [];

  return (
    <details
      className="my-2 rounded-md border border-border bg-muted/30 px-3 py-2 text-xs text-muted-foreground"
      open
    >
      <summary className="cursor-pointer select-none">
        🔎 Searched ingested episodes for{" "}
        <span className="font-mono text-foreground">“{args.query ?? ""}”</span>
        {" — "}
        {chunks.length > 0
          ? `${chunks.length} chunk${chunks.length === 1 ? "" : "s"}`
          : "running…"}
      </summary>
      {chunks.length > 0 && (
        <ol className="mt-2 space-y-1.5 pl-1">
          {chunks.map((c, i) => (
            <li key={`${c.citation}-${i}`} className="flex gap-2">
              <span className="shrink-0 font-mono text-foreground">
                {c.citation}
              </span>
              <span className="flex-1">
                <span className="text-foreground">{c.episode_title}</span>
                <span className="ml-1 text-muted-foreground">
                  @ {formatTime(c.start_time)}–{formatTime(c.end_time)}
                </span>
                <span className="ml-2 text-muted-foreground">
                  ({c.score.toFixed(2)})
                </span>
              </span>
            </li>
          ))}
        </ol>
      )}
    </details>
  );
}

function ToolCallFallback(props: {
  toolName?: string;
  args?: unknown;
  result?: unknown;
}) {
  return (
    <details className="my-2 rounded-md border border-amber-400/50 bg-amber-400/10 px-3 py-2 text-xs">
      <summary className="cursor-pointer select-none text-amber-300">
        🛠 Tool call: <span className="font-mono">{props.toolName ?? "?"}</span>
      </summary>
      <pre className="mt-2 whitespace-pre-wrap break-all text-[11px] text-muted-foreground">
        args = {JSON.stringify(props.args, null, 2)}
        {"\n"}result = {JSON.stringify(props.result, null, 2)}
      </pre>
    </details>
  );
}

function AssistantMessage() {
  return (
    <MessagePrimitive.Root className="flex px-4 py-2">
      <div className="rounded-2xl bg-card text-card-foreground px-4 py-2 max-w-[80%] border border-border">
        <MessagePrimitive.Parts
          components={{
            tools: {
              by_name: {
                search_chunks: SearchChunksDisplay,
              },
              Fallback: ToolCallFallback,
            },
          }}
        />
      </div>
    </MessagePrimitive.Root>
  );
}

function Thread() {
  return (
    <ThreadPrimitive.Root className="flex flex-col h-full bg-background text-foreground">
      <ThreadPrimitive.Viewport className="flex flex-1 flex-col overflow-hidden">
        <div className="flex-1 overflow-y-auto">
          <ThreadPrimitive.Empty>
            <div className="flex h-full items-center justify-center text-muted-foreground">
              <p>Ask Scott a question about the ingested jazz podcasts.</p>
            </div>
          </ThreadPrimitive.Empty>
          <ThreadPrimitive.Messages
            components={{
              UserMessage,
              AssistantMessage,
            }}
          />
        </div>

        <ThreadPrimitive.ViewportFooter className="border-t border-border bg-card">
          <ComposerPrimitive.Root className="flex items-end gap-2 p-3">
            <ComposerPrimitive.Input
              autoFocus
              placeholder="Ask Scott…"
              className="flex-1 resize-none rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
              rows={1}
            />
            <ThreadPrimitive.If running={false}>
              <ComposerPrimitive.Send className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90">
                Send
              </ComposerPrimitive.Send>
            </ThreadPrimitive.If>
            <ThreadPrimitive.If running>
              <ComposerPrimitive.Cancel className="rounded-md bg-destructive px-4 py-2 text-sm font-medium text-destructive-foreground hover:opacity-90">
                Stop
              </ComposerPrimitive.Cancel>
            </ThreadPrimitive.If>
          </ComposerPrimitive.Root>
        </ThreadPrimitive.ViewportFooter>
      </ThreadPrimitive.Viewport>
    </ThreadPrimitive.Root>
  );
}

function ThreadListItem() {
  return (
    <ThreadListItemPrimitive.Root className="group flex items-center gap-2 rounded-md px-2 py-1.5 hover:bg-accent data-[active]:bg-accent">
      <ThreadListItemPrimitive.Trigger className="flex-1 truncate text-left text-sm text-foreground">
        <ThreadListItemPrimitive.Title fallback="New chat" />
      </ThreadListItemPrimitive.Trigger>
    </ThreadListItemPrimitive.Root>
  );
}

function ThreadList() {
  return (
    <ThreadListPrimitive.Root className="flex flex-1 flex-col gap-1 overflow-y-auto">
      <ThreadListPrimitive.New className="mb-2 rounded-md border border-border bg-background px-3 py-1.5 text-sm text-foreground hover:bg-accent">
        + New conversation
      </ThreadListPrimitive.New>
      <ThreadListPrimitive.Items components={{ ThreadListItem }} />
    </ThreadListPrimitive.Root>
  );
}

function App() {
  const agent = useMemo(
    () =>
      new HttpAgent({
        url: "/chat/agent/",
        headers: {
          "X-Requested-With": "fetch",
          "X-CSRFToken": getCsrfToken() ?? "",
        },
      }),
    [],
  );

  const threadState = useMemo(() => initialThreadState(), []);
  const threadList = useMemo(
    () => buildThreadListAdapter(threadState),
    [threadState],
  );
  const history = useMemo(
    () => buildHistoryAdapter(threadState),
    [threadState],
  );

  const runtime = useAgUiRuntime({
    agent,
    adapters: { threadList, history },
    showThinking: true,
  });

  const onSignOut = useCallback(() => {
    signOut();
  }, []);

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <div className="flex h-full w-full bg-background text-foreground">
        <aside className="hidden sm:flex w-64 shrink-0 flex-col border-r border-border p-2">
          <header className="px-2 py-3 text-sm font-semibold text-muted-foreground">
            Scott
          </header>
          <ThreadList />
          <footer className="mt-auto px-2 py-3 text-xs text-muted-foreground">
            <button
              type="button"
              onClick={onSignOut}
              className="text-left hover:text-foreground"
            >
              Sign out
            </button>
          </footer>
        </aside>
        <main className="flex-1 flex flex-col min-w-0">
          <Thread />
        </main>
      </div>
    </AssistantRuntimeProvider>
  );
}

const root = document.getElementById("scott-root");
if (root) {
  createRoot(root).render(<App />);
}
