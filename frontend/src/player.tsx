// One audio player for the whole page, docked at the bottom.
//
// One, not an <audio> per row: a duplicate scan run with --skip-fingerprint can
// put thousands of tracks on screen, and one element per row would be thousands
// of media elements. It also makes A/B comparison work: switching to another
// track of the same group keeps the playback position, so the two files of a
// duplicate pair can be heard at the same moment.
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { audioUrl } from "./api";
import { baseName, extension } from "./format";

export interface PlayItem {
  path: string;
  title: string;
  subtitle?: string;
  /** Tracks sharing a group keep the playback position when switched between. */
  group?: string;
}

interface Player {
  current: PlayItem | null;
  playing: boolean;
  play: (item: PlayItem) => void;
  stop: () => void;
}

const PlayerContext = createContext<Player | null>(null);

export function usePlayer(): Player {
  const player = useContext(PlayerContext);
  if (!player) throw new Error("usePlayer outside PlayerProvider");
  return player;
}

export function PlayerProvider({ children }: { children: ReactNode }) {
  const audio = useRef<HTMLAudioElement>(null);
  const seekTo = useRef<number | null>(null);
  const [current, setCurrent] = useState<PlayItem | null>(null);
  const [playing, setPlaying] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const play = useCallback(
    (item: PlayItem) => {
      const el = audio.current;
      if (current && el && current.path === item.path) {
        if (el.paused) void el.play().catch(() => undefined);
        else el.pause();
        return;
      }
      seekTo.current =
        current && el && item.group && current.group === item.group && el.currentTime > 0 ? el.currentTime : null;
      setError(null);
      setCurrent(item);
    },
    [current],
  );

  const stop = useCallback(() => {
    audio.current?.pause();
    setCurrent(null);
  }, []);

  useEffect(() => {
    const el = audio.current;
    if (!el || !current) return;
    el.src = audioUrl(current.path);
    el.load();
    void el.play().catch(() => undefined);
  }, [current]);

  return (
    <PlayerContext.Provider value={{ current, playing, play, stop }}>
      {children}
      <div className={`player ${current ? "open" : ""}`} aria-hidden={!current}>
        <div className="player-label">
          {current && (
            <>
              <strong title={current.path}>{current.title || baseName(current.path)}</strong>
              <span className="muted">
                {current.subtitle ?? ""}
                {current.group ? " · switching within this group keeps the position" : ""}
              </span>
              {error && <span className="error-text">{error}</span>}
            </>
          )}
        </div>
        <audio
          ref={audio}
          controls
          preload="none"
          onPlay={() => setPlaying(true)}
          onPause={() => setPlaying(false)}
          onEnded={() => setPlaying(false)}
          onLoadedMetadata={(e) => {
            const at = seekTo.current;
            seekTo.current = null;
            if (at !== null && at < e.currentTarget.duration) e.currentTarget.currentTime = at;
          }}
          onError={() => {
            if (!current) return;
            const ext = extension(current.path);
            setError(
              ext === "aif" || ext === "aiff"
                ? "This browser cannot play AIFF."
                : "Could not play this file (missing, moved, or a format this browser cannot decode).",
            );
          }}
        />
        <button className="ghost" onClick={stop} title="Close player" aria-label="Close player">
          ✕
        </button>
      </div>
    </PlayerContext.Provider>
  );
}

export function PlayButton({ item }: { item: PlayItem }) {
  const { current, playing, play } = usePlayer();
  const active = current?.path === item.path;
  return (
    <button
      className={`play ${active ? "active" : ""}`}
      onClick={() => play(item)}
      title={active && playing ? "Pause" : `Play ${baseName(item.path)}`}
      aria-label={active && playing ? "Pause" : "Play"}
    >
      {active && playing ? "❚❚" : "▶"}
    </button>
  );
}
