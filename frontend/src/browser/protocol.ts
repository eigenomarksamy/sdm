// Messages between the page (browser/api.ts) and the Python worker (browser/worker.ts).
import type { Command, JobOutput } from "../api";

/** What `build_browser.py` writes to python.json: where everything is and how big. */
export interface Manifest {
  /** Directory of the self-hosted Pyodide release, relative to the site root. */
  pyodide: string;
  /** Pyodide's own packages, by name. */
  packages: string[];
  /**
   * Pyodide's lock file, cut down to those packages. Carried here rather than
   * beside the release so the release's directory holds only files that never
   * change, and can be cached as such.
   */
  lock: object;
  /** Our wheels, by file name, under wheels/. */
  wheels: string[];
  /** Byte size of every file the boot downloads, keyed by URL path: the progress bar's total. */
  bytes: Record<string, number>;
}

/** What a picked folder is cut down to before it is mounted. From `sdm.browser.boot`. */
export interface MountRules {
  audio_exts: string[];
  analysis_dir: string;
}

export interface BootInfo {
  version: string;
  out_root: string;
  music_root: string;
  playlist_root: string;
  mount: MountRules;
  commands: Command[];
  offline: string[];
}

export interface MountedFolder {
  path: string;
  files: number;
  audio: number;
  analysis: number;
}

/** A file under the output root, carried to the page so reports outlive the worker. */
export interface OutFile {
  path: string;
  mtime: number;
  data: ArrayBuffer;
}

/**
 * A run's result. A cancelled run changed nothing: the worker dropped what it
 * wrote, so `outputs` and `changed` are empty. `exit_code` is null for a run
 * cancelled before it started.
 */
export interface RunResult {
  exit_code: number | null;
  cancelled: boolean;
  outputs: JobOutput[];
  changed: OutFile[];
}

/**
 * The cancel channel: an Int32Array over a SharedArrayBuffer the page and the
 * worker both hold, when the page is cross-origin isolated. The page writes the
 * job's number to CANCEL_JOB, then SIGINT to SIGNAL, the slot Pyodide polls
 * while Python runs. Shared memory because a message would wait behind the run.
 */
export const SIGNAL = 0;
export const CANCEL_JOB = 1;
export const SIGINT = 2;

export type Staged = { rel: string; file: File };

export type ToWorker =
  | { type: "init"; id: number; base: string; blockSize: number | null; control: Int32Array | null }
  | { type: "call"; id: number; name: string; args: Record<string, unknown> }
  | { type: "run"; id: number; job: string; command: string; argv: string[] }
  | { type: "stage"; id: number; files: Staged[] }
  | { type: "mount"; id: number; name: string; handle?: FileSystemDirectoryHandle }
  | { type: "csv"; id: number; name: string; file: File }
  | { type: "restore"; id: number; files: { path: string; mtime: number; data: Blob }[] };

export type FromWorker =
  | { type: "reply"; id: number; ok: true; data: unknown }
  | { type: "reply"; id: number; ok: false; status: number; error: string }
  | { type: "boot"; step: string; loaded: number; total: number }
  | { type: "line"; job: string; stream: "out" | "err"; text: string }
  | { type: "progress"; id: number; seen: number; kept: number };
