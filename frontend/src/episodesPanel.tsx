import { useCallback, useEffect, useState } from "react";

import { useAudioPlayer } from "./audioPlayer";
import { formatTime } from "./time";

type Episode = {
  id: number;
  title: string;
  duration: number | null;
  published_at: string | null;
  audio_url: string;
  image_url: string;
  description: string;
};

type FetchState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; episodes: Episode[] };

export function EpisodesPanel({
  collapsed,
  onToggle,
}: {
  collapsed: boolean;
  onToggle: () => void;
}) {
  const [state, setState] = useState<FetchState>({ status: "loading" });
  const [reloadKey, setReloadKey] = useState(0);
  const { play } = useAudioPlayer();

  useEffect(() => {
    const controller = new AbortController();
    setState({ status: "loading" });
    fetch("/episodes/api/episodes/", {
      credentials: "same-origin",
      signal: controller.signal,
    })
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((data: { episodes: Episode[] }) => {
        setState({ status: "ready", episodes: data.episodes ?? [] });
      })
      .catch((err: unknown) => {
        if (err instanceof DOMException && err.name === "AbortError") return;
        const msg = err instanceof Error ? err.message : String(err);
        setState({ status: "error", message: msg });
      });
    return () => controller.abort();
  }, [reloadKey]);

  const onRetry = useCallback(() => setReloadKey((k) => k + 1), []);

  if (collapsed) {
    return (
      <aside
        className="hidden md:flex w-10 shrink-0 flex-col border-l border-border"
        aria-label="Episodes panel collapsed"
      >
        <button
          type="button"
          onClick={onToggle}
          aria-label="Open episodes panel"
          className="flex h-full w-full items-center justify-center text-muted-foreground hover:bg-accent hover:text-foreground"
        >
          <svg
            viewBox="0 0 24 24"
            width="18"
            height="18"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <polyline points="11 17 6 12 11 7" />
            <polyline points="18 17 13 12 18 7" />
          </svg>
        </button>
      </aside>
    );
  }

  return (
    <aside
      className="hidden md:flex w-80 shrink-0 flex-col border-l border-border"
      aria-label="Episodes panel"
    >
      <header className="flex items-center justify-between px-3 py-2 border-b border-border">
        <h2 className="text-sm font-medium text-foreground">Episodes</h2>
        <button
          type="button"
          onClick={onToggle}
          aria-label="Close episodes panel"
          className="inline-flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground"
        >
          <svg
            viewBox="0 0 24 24"
            width="16"
            height="16"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <polyline points="13 17 18 12 13 7" />
            <polyline points="6 17 11 12 6 7" />
          </svg>
        </button>
      </header>
      <div className="flex-1 overflow-y-auto p-2">
        {state.status === "loading" && (
          <p className="px-2 py-3 text-xs text-muted-foreground">Loading…</p>
        )}
        {state.status === "error" && (
          <div className="px-2 py-3 text-xs text-muted-foreground">
            <p className="mb-2">Failed to load: {state.message}</p>
            <button
              type="button"
              onClick={onRetry}
              className="rounded-md border border-border px-2 py-1 hover:bg-accent hover:text-foreground"
            >
              Retry
            </button>
          </div>
        )}
        {state.status === "ready" && state.episodes.length === 0 && (
          <p className="px-2 py-3 text-xs text-muted-foreground">
            No ingested episodes yet.
          </p>
        )}
        {state.status === "ready" && state.episodes.length > 0 && (
          <ul className="space-y-1">
            {state.episodes.map((ep) => (
              <li key={ep.id}>
                <EpisodeCard
                  episode={ep}
                  onPlay={() =>
                    play(
                      {
                        episodeId: ep.id,
                        audioUrl: ep.audio_url,
                        title: ep.title,
                        imageUrl: ep.image_url,
                        durationSec: ep.duration ?? undefined,
                      },
                      0,
                    )
                  }
                />
              </li>
            ))}
          </ul>
        )}
      </div>
    </aside>
  );
}

function EpisodeCard({
  episode,
  onPlay,
}: {
  episode: Episode;
  onPlay: () => void;
}) {
  const disabled = !episode.audio_url;
  return (
    <button
      type="button"
      onClick={onPlay}
      disabled={disabled}
      className="flex w-full gap-2 rounded-md p-2 text-left hover:bg-accent disabled:cursor-not-allowed disabled:opacity-60"
      title={disabled ? "No audio available" : "Play from start"}
    >
      {episode.image_url ? (
        <img
          src={episode.image_url}
          alt=""
          className="h-12 w-12 shrink-0 rounded object-cover"
        />
      ) : (
        <div className="h-12 w-12 shrink-0 rounded bg-muted" aria-hidden />
      )}
      <div className="flex-1 min-w-0">
        <div className="line-clamp-2 text-sm text-foreground">
          {episode.title || "(untitled)"}
        </div>
        <div className="mt-1 flex items-center gap-2 text-xs text-muted-foreground">
          {episode.published_at && <span>{episode.published_at}</span>}
          {episode.duration != null && <span>{formatTime(episode.duration)}</span>}
        </div>
      </div>
    </button>
  );
}
