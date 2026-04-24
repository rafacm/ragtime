import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

export type AudioTrack = {
  episodeId: number;
  audioUrl: string;
  title: string;
  imageUrl?: string;
  durationSec?: number;
};

type AudioPlayerState = {
  currentTrack: AudioTrack | null;
  isPlaying: boolean;
  isMinimized: boolean;
  currentTimeSec: number;
  durationSec: number;
  play: (track: AudioTrack, atSec?: number) => void;
  pause: () => void;
  resume: () => void;
  seek: (sec: number) => void;
  minimize: () => void;
  expand: () => void;
  close: () => void;
};

const AudioPlayerContext = createContext<AudioPlayerState | null>(null);

export function useAudioPlayer(): AudioPlayerState {
  const ctx = useContext(AudioPlayerContext);
  if (!ctx) {
    throw new Error("useAudioPlayer must be used inside <AudioPlayerProvider>");
  }
  return ctx;
}

export function AudioPlayerProvider({ children }: { children: ReactNode }) {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  if (audioRef.current === null && typeof Audio !== "undefined") {
    audioRef.current = new Audio();
    audioRef.current.preload = "metadata";
  }

  const [currentTrack, setCurrentTrack] = useState<AudioTrack | null>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [isMinimized, setIsMinimized] = useState(false);
  const [currentTimeSec, setCurrentTimeSec] = useState(0);
  const [durationSec, setDurationSec] = useState(0);

  // Bound seek we want to apply as soon as metadata is loaded.
  const pendingSeekRef = useRef<number | null>(null);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;
    const onTime = () => setCurrentTimeSec(audio.currentTime);
    const onMeta = () => {
      setDurationSec(Number.isFinite(audio.duration) ? audio.duration : 0);
      const pending = pendingSeekRef.current;
      if (pending !== null) {
        audio.currentTime = pending;
        pendingSeekRef.current = null;
      }
    };
    const onPlay = () => setIsPlaying(true);
    const onPause = () => setIsPlaying(false);
    const onEnded = () => setIsPlaying(false);
    audio.addEventListener("timeupdate", onTime);
    audio.addEventListener("loadedmetadata", onMeta);
    audio.addEventListener("play", onPlay);
    audio.addEventListener("pause", onPause);
    audio.addEventListener("ended", onEnded);
    return () => {
      audio.removeEventListener("timeupdate", onTime);
      audio.removeEventListener("loadedmetadata", onMeta);
      audio.removeEventListener("play", onPlay);
      audio.removeEventListener("pause", onPause);
      audio.removeEventListener("ended", onEnded);
    };
  }, []);

  const play = useCallback(
    (track: AudioTrack, atSec: number = 0) => {
      const audio = audioRef.current;
      if (!audio || !track.audioUrl) return;

      setCurrentTrack(track);
      setIsMinimized(false);
      if (track.durationSec !== undefined) {
        setDurationSec(track.durationSec);
      }

      const sameSource = audio.src && audio.src === toAbsoluteUrl(track.audioUrl);
      if (sameSource) {
        audio.currentTime = atSec;
        void audio.play();
        return;
      }

      pendingSeekRef.current = atSec;
      audio.src = track.audioUrl;
      setCurrentTimeSec(atSec);
      void audio.play();
    },
    [],
  );

  const pause = useCallback(() => {
    audioRef.current?.pause();
  }, []);

  const resume = useCallback(() => {
    void audioRef.current?.play();
  }, []);

  const seek = useCallback((sec: number) => {
    const audio = audioRef.current;
    if (!audio) return;
    audio.currentTime = sec;
    setCurrentTimeSec(sec);
  }, []);

  const minimize = useCallback(() => setIsMinimized(true), []);
  const expand = useCallback(() => setIsMinimized(false), []);

  const close = useCallback(() => {
    const audio = audioRef.current;
    if (audio) {
      audio.pause();
      audio.removeAttribute("src");
      audio.load();
    }
    setCurrentTrack(null);
    setIsPlaying(false);
    setIsMinimized(false);
    setCurrentTimeSec(0);
    setDurationSec(0);
    pendingSeekRef.current = null;
  }, []);

  const value = useMemo<AudioPlayerState>(
    () => ({
      currentTrack,
      isPlaying,
      isMinimized,
      currentTimeSec,
      durationSec,
      play,
      pause,
      resume,
      seek,
      minimize,
      expand,
      close,
    }),
    [
      currentTrack,
      isPlaying,
      isMinimized,
      currentTimeSec,
      durationSec,
      play,
      pause,
      resume,
      seek,
      minimize,
      expand,
      close,
    ],
  );

  return (
    <AudioPlayerContext.Provider value={value}>
      {children}
    </AudioPlayerContext.Provider>
  );
}

function toAbsoluteUrl(url: string): string {
  try {
    return new URL(url, window.location.href).href;
  } catch {
    return url;
  }
}
