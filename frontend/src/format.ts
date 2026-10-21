// Small display helpers shared by the views.
import { browser } from "./api";

export const AUDIO_EXTS = [".mp3", ".m4a", ".flac", ".aif", ".aiff", ".wav", ".ogg"];

// The server only listens on this machine, so the browser's platform is the
// server's: what counts as an absolute path here is what the server can open.
const WINDOWS = navigator.userAgent.includes("Windows");

/**
 * An audio file this machine can play: absolute here, with an audio extension.
 * Absolute matters — analyze's `device_path` (`/Contents/…/x.mp3`) is a path on
 * the USB as Rekordbox records it, not a file the server can find.
 */
export function isAudioPath(value: string): boolean {
  // The browser build plays from folders picked in the tab, at their mount paths.
  if (browser) return browser.isPlayable(value);
  const v = value.toLowerCase();
  const absolute = WINDOWS ? /^([a-z]:[\\/]|\\\\)/.test(v) : v.startsWith("/");
  return absolute && AUDIO_EXTS.some((ext) => v.endsWith(ext));
}

export function baseName(path: string): string {
  return path.split(/[\\/]/).pop() ?? path;
}

export function dirName(path: string): string {
  const i = Math.max(path.lastIndexOf("\\"), path.lastIndexOf("/"));
  return i >= 0 ? path.slice(0, i) : "";
}

export function extension(path: string): string {
  const name = baseName(path);
  const i = name.lastIndexOf(".");
  return i > 0 ? name.slice(i + 1).toLowerCase() : "";
}

export function bytes(n: number): string {
  if (n < 1024) return `${n} B`;
  const units = ["KB", "MB", "GB"];
  let v = n / 1024;
  let u = 0;
  while (v >= 1024 && u < units.length - 1) {
    v /= 1024;
    u++;
  }
  return `${v.toFixed(v < 10 ? 1 : 0)} ${units[u]}`;
}

/** Seconds as m:ss, or m:ss.s with `precise` — duplicate durations differ by fractions. */
export function clock(seconds: number | null | undefined, precise = false): string {
  if (seconds === null || seconds === undefined || !isFinite(seconds)) return "";
  const m = Math.floor(seconds / 60);
  const s = seconds - m * 60;
  const ss = precise ? s.toFixed(1).padStart(4, "0") : String(Math.floor(s)).padStart(2, "0");
  return `${m}:${ss}`;
}

export function ago(epochSeconds: number): string {
  const diff = Date.now() / 1000 - epochSeconds;
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)} min ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} h ago`;
  if (diff < 86400 * 30) return `${Math.floor(diff / 86400)} d ago`;
  return new Date(epochSeconds * 1000).toLocaleDateString();
}

export function elapsed(start: number, end: number | null): string {
  const total = Math.max(0, Math.round((end ?? Date.now() / 1000) - start));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  return h ? `${h}h ${m}m ${s}s` : m ? `${m}m ${s}s` : `${s}s`;
}

export function plural(n: number, word: string, many = `${word}s`): string {
  return `${n.toLocaleString()} ${n === 1 ? word : many}`;
}

export async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

/** localStorage that never throws: private windows and blocked storage just forget. */
export const store = {
  get<T>(key: string, fallback: T): T {
    try {
      const raw = window.localStorage.getItem(key);
      return raw === null ? fallback : (JSON.parse(raw) as T);
    } catch {
      return fallback;
    }
  },
  set(key: string, value: unknown): void {
    try {
      window.localStorage.setItem(key, JSON.stringify(value));
    } catch {
      // Not remembered; nothing depends on it.
    }
  },
};
