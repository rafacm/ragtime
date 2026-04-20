import "./styles.css";

import { HttpAgent } from "@ag-ui/client";
import {
  AssistantRuntimeProvider,
  Thread,
  ThreadList,
} from "@assistant-ui/react";
import { useAgUiRuntime } from "@assistant-ui/react-ag-ui";
import { useMemo } from "react";
import { createRoot } from "react-dom/client";

import { buildThreadListAdapter, getCsrfToken } from "./threadAdapter";

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

  const threadList = useMemo(() => buildThreadListAdapter(), []);

  const runtime = useAgUiRuntime({
    agent,
    adapters: { threadList },
    showThinking: true,
  });

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <div className="flex h-full w-full">
        <aside className="hidden sm:flex w-64 shrink-0 flex-col border-r border-slate-800 p-2">
          <header className="px-2 py-3 text-sm font-semibold text-slate-300">
            Scott
          </header>
          <ThreadList />
          <footer className="mt-auto px-2 py-3 text-xs text-slate-500">
            <a href="/accounts/logout/" className="hover:text-slate-300">
              Sign out
            </a>
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
