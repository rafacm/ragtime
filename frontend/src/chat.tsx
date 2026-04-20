import "./styles.css";

import { HttpAgent } from "@ag-ui/client";
import {
  AssistantRuntimeProvider,
  Thread,
  ThreadList,
} from "@assistant-ui/react";
import { useAgUiRuntime } from "@assistant-ui/react-ag-ui";
import { useMemo, useCallback } from "react";
import { createRoot } from "react-dom/client";

import {
  buildHistoryAdapter,
  buildThreadListAdapter,
  getCsrfToken,
} from "./threadAdapter";

async function signOut() {
  await fetch("/accounts/logout/", {
    method: "POST",
    credentials: "same-origin",
    headers: { "X-CSRFToken": getCsrfToken() ?? "" },
  });
  window.location.assign("/accounts/login/");
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

  const threadState = useMemo(() => ({ threadId: null as string | null }), []);
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
      <div className="flex h-full w-full">
        <aside className="hidden sm:flex w-64 shrink-0 flex-col border-r border-slate-800 p-2">
          <header className="px-2 py-3 text-sm font-semibold text-slate-300">
            Scott
          </header>
          <ThreadList />
          <footer className="mt-auto px-2 py-3 text-xs text-slate-500">
            <button
              type="button"
              onClick={onSignOut}
              className="text-left hover:text-slate-300"
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
