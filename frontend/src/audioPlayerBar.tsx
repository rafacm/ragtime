import type { ChangeEvent } from "react";

import { useAudioPlayer } from "./audioPlayer";
import { formatTime } from "./time";

export function AudioPlayerBar() {
  const {
    currentTrack,
    isPlaying,
    isMinimized,
    currentTimeSec,
    durationSec,
    pause,
    resume,
    seek,
    minimize,
    expand,
    close,
  } = useAudioPlayer();

  if (!currentTrack) return null;

  const onSeek = (e: ChangeEvent<HTMLInputElement>) => {
    seek(parseFloat(e.target.value));
  };

  const togglePlay = () => (isPlaying ? pause() : resume());

  if (isMinimized) {
    return (
      <div
        role="region"
        aria-label="Audio player"
        className="flex items-center gap-2 border-t border-border bg-card px-3 py-1.5 text-xs text-foreground"
      >
        <span className="truncate flex-1">{currentTrack.title}</span>
        <PlayPauseButton isPlaying={isPlaying} onClick={togglePlay} />
        <IconButton onClick={expand} ariaLabel="Expand player">
          <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="4 14 10 14 10 20" /><polyline points="20 10 14 10 14 4" /><line x1="14" y1="10" x2="21" y2="3" /><line x1="10" y1="14" x2="3" y2="21" /></svg>
        </IconButton>
        <IconButton onClick={close} ariaLabel="Close player">
          <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" /></svg>
        </IconButton>
      </div>
    );
  }

  return (
    <div
      role="region"
      aria-label="Audio player"
      className="flex items-center gap-3 border-t border-border bg-card px-3 py-2 text-sm text-foreground"
    >
      {currentTrack.imageUrl ? (
        <img
          src={currentTrack.imageUrl}
          alt=""
          className="h-10 w-10 shrink-0 rounded object-cover"
        />
      ) : (
        <div className="h-10 w-10 shrink-0 rounded bg-muted" aria-hidden />
      )}
      <div className="flex-1 min-w-0">
        <div className="truncate text-sm font-medium">{currentTrack.title}</div>
        <div className="flex items-center gap-2">
          <span className="shrink-0 font-mono text-xs text-muted-foreground tabular-nums">
            {formatTime(currentTimeSec)}
          </span>
          <input
            type="range"
            min={0}
            max={durationSec || 0}
            step={0.1}
            value={Math.min(currentTimeSec, durationSec || 0)}
            onChange={onSeek}
            aria-label="Seek"
            className="flex-1 accent-primary"
          />
          <span className="shrink-0 font-mono text-xs text-muted-foreground tabular-nums">
            {formatTime(durationSec)}
          </span>
        </div>
      </div>
      <PlayPauseButton isPlaying={isPlaying} onClick={togglePlay} />
      <IconButton onClick={minimize} ariaLabel="Minimize player">
        <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="5" y1="12" x2="19" y2="12" /></svg>
      </IconButton>
      <IconButton onClick={close} ariaLabel="Close player">
        <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" /></svg>
      </IconButton>
    </div>
  );
}

function PlayPauseButton({
  isPlaying,
  onClick,
}: {
  isPlaying: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={isPlaying ? "Pause" : "Play"}
      className="inline-flex h-8 w-8 items-center justify-center rounded-full bg-primary text-primary-foreground hover:opacity-90"
    >
      {isPlaying ? (
        <svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor"><rect x="6" y="5" width="4" height="14" rx="1" /><rect x="14" y="5" width="4" height="14" rx="1" /></svg>
      ) : (
        <svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor"><polygon points="7,5 19,12 7,19" /></svg>
      )}
    </button>
  );
}

function IconButton({
  onClick,
  ariaLabel,
  children,
}: {
  onClick: () => void;
  ariaLabel: string;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={ariaLabel}
      className="inline-flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground"
    >
      {children}
    </button>
  );
}
