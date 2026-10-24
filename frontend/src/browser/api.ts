// The browser build's API: every call src/api.ts makes to `sdm web`, answered
// in the tab. Vite swaps this module in for src/api.ts under `--mode browser`
// (vite.config.ts), so the pages and views run unchanged against it.
//
// Python lives in a worker (worker.ts). What lives here is what has to outlive
// it or answer while it is busy: job records and their logs (polled by the job
// page exactly as from the server), a copy of every report (a cancel can end the
// worker, and the report list must open while a run blocks it), and the folders
// the visitor picked (to mount again after a restart, and to play audio from).
// The Spotify login is spotify.ts's; each run of a playlist command is handed it.
import { ApiError } from "../api";
import type {
  BootState,
  BrowserHooks,
  Command,
  FormValues,
  JobDetail,
  JobOutput,
  JobStatus,
  JobSummary,
  LogLine,
  PickProgress,
  ReportFile,
  Session,
  TablePage,
} from "../api";
import { keepForMount, mountName } from "./files";
import { CANCEL_JOB, SIGINT, SIGNAL } from "./protocol";
import type { BootInfo, FromWorker, MountedFolder, RunResult, Staged, ToWorker } from "./protocol";
import { spotify } from "./spotify";

export { ApiError };

declare global {
  interface Window {
    showDirectoryPicker?: (options?: { id?: string; mode?: "read" | "readwrite" }) => Promise<FileSystemDirectoryHandle>;
  }
}

/** Log lines kept per job, as `web/jobs.py` keeps them. */
const MAX_LINES = 20_000;

/** Files per message when handing a picked folder to the worker; small enough to show progress between. */
const STAGE_CHUNK = 1_000;

/** How long a cancelled command gets to stop before Python is restarted instead. */
const CANCEL_GRACE_MS = 5_000;

/** How often a cancel is signalled again meanwhile; see `_on_cancel` in sdm/browser.py. */
const RESIGNAL_MS = 250;

const BASE = new URL(import.meta.env.BASE_URL, window.location.href).href;

/** `?block=N` sets the read cache's block size, 0 turns it off. For measuring; see worker.ts. */
const BLOCK_KNOB = new URLSearchParams(window.location.search).get("block");

// --- the worker -----------------------------------------------------------------------

type Request = ToWorker extends infer M ? (M extends { id: number } ? Omit<M, "id"> : never) : never;

class Python {
  private worker: Worker;
  private nextId = 1;
  /**
   * The cancel channel (protocol.ts). SharedArrayBuffer exists only on a
   * cross-origin isolated page (`_headers`); without it, a cancel restarts Python.
   */
  private control = crossOriginIsolated ? new Int32Array(new SharedArrayBuffer(8)) : null;
  private waiting = new Map<
    number,
    { resolve: (value: unknown) => void; reject: (error: unknown) => void; progress?: (seen: number, kept: number) => void }
  >();
  /** Booted, and — after a restart — every folder mounted and report restored again. */
  ready: Promise<BootInfo>;

  constructor(onBoot: (state: BootState) => void, onLine: (job: string, line: LogLine) => void) {
    this.worker = new Worker(new URL("./worker.ts", import.meta.url), { type: "module" });
    this.worker.onmessage = ({ data }: MessageEvent<FromWorker>) => {
      if (data.type === "boot") onBoot({ step: data.step, loaded: data.loaded, total: data.total, error: null });
      else if (data.type === "line") onLine(data.job, [data.stream, data.text]);
      else if (data.type === "progress") this.waiting.get(data.id)?.progress?.(data.seen, data.kept);
      else {
        const waiter = this.waiting.get(data.id);
        this.waiting.delete(data.id);
        if (!waiter) return;
        if (data.ok) waiter.resolve(data.data);
        else waiter.reject(new ApiError(data.status, data.error));
      }
    };
    // A worker that fails to load (an old browser, a blocked script) says so only here.
    this.worker.onerror = (event) => this.fail(new Error(event.message || "the Python worker could not start"));
    this.ready = this.send<BootInfo>({
      type: "init",
      base: BASE,
      blockSize: BLOCK_KNOB === null ? null : Number(BLOCK_KNOB),
      control: this.control,
    });
  }

  /** Ask Python to stop job `job`'s command, as Ctrl-C would. False if it cannot be asked. */
  interrupt(job: number): boolean {
    if (!this.control) return false;
    Atomics.store(this.control, CANCEL_JOB, job);
    Atomics.store(this.control, SIGNAL, SIGINT);
    return true;
  }

  send<T>(message: Request, transfer: Transferable[] = [], progress?: (seen: number, kept: number) => void): Promise<T> {
    const id = this.nextId++;
    return new Promise<T>((resolve, reject) => {
      this.waiting.set(id, { resolve: resolve as (value: unknown) => void, reject, progress });
      this.worker.postMessage({ ...message, id } as ToWorker, transfer);
    });
  }

  terminate(): void {
    this.worker.terminate();
    this.fail(new ApiError(499, "Python was restarted"));
  }

  private fail(error: unknown): void {
    for (const waiter of this.waiting.values()) waiter.reject(error);
    this.waiting.clear();
  }
}

let bootState: BootState = { step: "Starting", loaded: 0, total: 0, error: null };
const bootListeners = new Set<(state: BootState) => void>();
function setBoot(state: BootState): void {
  bootState = state;
  for (const listener of bootListeners) listener(state);
}

let python = new Python(setBoot, appendLine);
let info: BootInfo | null = null;
watchBoot(python);

function watchBoot(instance: Python): void {
  instance.ready.then(
    (booted) => {
      info = booted;
      setBoot({ ...bootState, step: "Ready", error: null });
    },
    (e: unknown) => setBoot({ ...bootState, error: e instanceof Error ? e.message : String(e) }),
  );
}

async function call<T>(name: string, args: Record<string, unknown> = {}): Promise<T> {
  const current = python;
  await current.ready;
  return current.send<T>({ type: "call", name, args });
}

// --- jobs ----------------------------------------------------------------------------

interface Job extends JobSummary {
  lines: LogLine[];
  first_line: number;
  outputs: JobOutput[];
}

const jobs: Job[] = [];
let starting = false;

function summary(job: Job): JobSummary {
  const { id, command, display, status, exit_code, started, ended, cancel_requested } = job;
  return { id, command, display, status, exit_code, started, ended, cancel_requested };
}

function detail(job: Job, since: number): JobDetail {
  const start = Math.max(since - job.first_line, 0);
  return {
    ...summary(job),
    lines: job.lines.slice(start),
    next: job.first_line + job.lines.length,
    dropped: Math.max(job.first_line - since, 0),
    outputs: job.outputs,
  };
}

function appendLine(id: string, line: LogLine): void {
  const job = jobs.find((j) => j.id === id);
  if (!job) return;
  job.lines.push(line);
  if (job.lines.length > MAX_LINES) {
    const drop = job.lines.length - MAX_LINES;
    job.lines.splice(0, drop);
    job.first_line += drop;
  }
}

function finish(job: Job, status: JobStatus, exitCode: number | null): void {
  job.status = status;
  job.exit_code = exitCode;
  job.ended = Date.now() / 1000;
}

function findJob(id: string): Job {
  const job = jobs.find((j) => j.id === id);
  if (!job) throw new ApiError(404, `no job ${id}`);
  return job;
}

// --- reports ---------------------------------------------------------------------------

interface Report {
  blob: Blob;
  mtime: number;
  url?: string;
}

/** Every file under the output root, by its path there ("/out/catalog/x.csv"). */
const reports = new Map<string, Report>();

const outRoot = () => info?.out_root ?? "/out";
const outPath = (path: string) => (path.startsWith("/") ? path : `${outRoot()}/${path}`);

function keepReports(result: RunResult): void {
  for (const file of result.changed) {
    dropReport(file.path);
    // Text types, so "Open raw" shows a report in the tab instead of downloading it.
    const type = file.path.endsWith(".json") ? "application/json" : "text/plain;charset=utf-8";
    reports.set(file.path, { blob: new Blob([file.data], { type }), mtime: file.mtime });
  }
}

function dropReport(path: string): void {
  const old = reports.get(path);
  if (old?.url) URL.revokeObjectURL(old.url);
  reports.delete(path);
}

function reportOrThrow(path: string): Report {
  const report = reports.get(outPath(path));
  if (!report) throw new ApiError(404, `no such report: ${path}`);
  return report;
}

// --- picked folders ------------------------------------------------------------------------

interface Mount {
  folder: MountedFolder;
  source: { kind: "handle"; handle: FileSystemDirectoryHandle } | { kind: "files"; files: Map<string, File> };
}

/** By mount path ("/music/Songs"). A pick of a folder with the same name replaces it. */
const mounts = new Map<string, Mount>();
let playing: string | null = null;

function mountFor(path: string): { mount: Mount; rel: string } | null {
  for (const [root, mount] of mounts) {
    if (path.startsWith(`${root}/`)) return { mount, rel: path.slice(root.length + 1) };
  }
  return null;
}

function describe(folder: MountedFolder): string {
  const parts = [`${folder.audio.toLocaleString()} audio file${folder.audio === 1 ? "" : "s"}`];
  if (folder.analysis) parts.push(`${folder.analysis.toLocaleString()} Rekordbox analysis files`);
  return parts.join(", ");
}

/** An `<input type=file>` the browser opens; resolves to what was chosen, or null. */
function chooseFiles(options: { directory: boolean; accept: string[] }): Promise<File[] | null> {
  return new Promise((resolve) => {
    const input = document.createElement("input");
    input.type = "file";
    input.hidden = true;
    input.dataset.sdmPicker = options.directory ? "dir" : "file";
    if (options.directory) input.webkitdirectory = true;
    if (options.accept.length) input.accept = options.accept.join(",");
    const done = (files: File[] | null) => {
      input.remove();
      resolve(files);
    };
    input.addEventListener("change", () => done(input.files ? Array.from(input.files) : null), { once: true });
    input.addEventListener("cancel", () => done(null), { once: true });
    document.body.append(input);
    input.click();
  });
}

async function pickFolder(
  onProgress: (progress: PickProgress) => void,
  fallback: boolean,
): Promise<{ path: string; summary: string } | null> {
  if (!fallback && window.showDirectoryPicker) {
    let handle: FileSystemDirectoryHandle;
    try {
      handle = await window.showDirectoryPicker({ id: "sdm-music", mode: "read" });
    } catch (e) {
      if (e instanceof DOMException && e.name === "AbortError") return null;
      throw e;
    }
    onProgress({ text: "Reading the folder…" });
    const current = python;
    await current.ready;
    const folder = await current.send<MountedFolder>({ type: "mount", name: handle.name, handle }, [], (seen, kept) =>
      onProgress({ text: `Reading the folder: ${seen.toLocaleString()} files looked at, ${kept.toLocaleString()} to read` }),
    );
    mounts.set(folder.path, { folder, source: { kind: "handle", handle } });
    return { path: folder.path, summary: describe(folder) };
  }

  const files = await chooseFiles({ directory: true, accept: [] });
  if (!files) return null;
  if (files.length === 0) throw new Error("That folder is empty.");
  const current = python;
  const { mount: rules } = await current.ready;
  const root = files[0].webkitRelativePath.split("/")[0];
  const kept: Staged[] = [];
  for (const file of files) {
    if (keepForMount(file.webkitRelativePath, rules)) kept.push({ rel: file.webkitRelativePath.slice(root.length + 1), file });
  }
  // Handed over in chunks: one message with every File would hold the page
  // still for seconds, with nothing to show for it.
  for (let i = 0; i < kept.length; i += STAGE_CHUNK) {
    onProgress({ text: `Handing ${kept.length.toLocaleString()} of ${files.length.toLocaleString()} files to Python`, done: i, total: kept.length });
    await current.send<number>({ type: "stage", files: kept.slice(i, i + STAGE_CHUNK) });
  }
  const folder = await current.send<MountedFolder>({ type: "mount", name: root });
  mounts.set(folder.path, { folder, source: { kind: "files", files: new Map(kept.map((k) => [k.rel, k.file])) } });
  return { path: folder.path, summary: describe(folder) };
}

/**
 * Cancel by ending the worker mid-run and starting another. Nothing it was
 * writing survives it, and the new one gets the page's copies of the reports.
 */
function restart(job: Job, why: string): void {
  python.terminate();
  appendLine(job.id, ["err", `cancelled: ${why} Earlier reports are kept.`]);
  finish(job, "cancelled", null);
  const next = new Python(() => undefined, appendLine);
  next.ready = remountAndRestore(next);
  python = next;
  watchBoot(next);
}

/** After a restart: mount every picked folder again and put the reports back. */
async function remountAndRestore(next: Python): Promise<BootInfo> {
  const booted = await next.ready;
  for (const { folder, source } of mounts.values()) {
    const name = folder.path.slice(booted.music_root.length + 1);
    if (source.kind === "handle") {
      await next.send({ type: "mount", name, handle: source.handle });
    } else {
      const files = [...source.files].map(([rel, file]) => ({ rel, file }));
      for (let i = 0; i < files.length; i += STAGE_CHUNK) await next.send({ type: "stage", files: files.slice(i, i + STAGE_CHUNK) });
      await next.send({ type: "mount", name });
    }
  }
  const files = [...reports].map(([path, r]) => ({ path, mtime: r.mtime, data: r.blob }));
  await next.send({ type: "restore", files });
  return booted;
}

// --- the API ------------------------------------------------------------------------------------

export const api = {
  session: async (): Promise<Session> => {
    const booted = await python.ready;
    return {
      version: booted.version,
      out_root: booted.out_root,
      tmp_root: "/tmp",
      cwd: "/",
      sep: "/",
      spotify_client_id: false,
      spotify_redirect_uri: spotify.redirectUri,
    };
  },
  commands: async (): Promise<Command[]> => (await python.ready).commands,
  jobs: async (): Promise<JobSummary[]> => [...jobs].reverse().map(summary),
  job: async (id: string, since = 0): Promise<JobDetail> => detail(findJob(id), since),

  startJob: async (command: string, values: FormValues): Promise<JobDetail> => {
    const running = jobs.find((j) => j.status === "running");
    if (running || starting) {
      const message = running
        ? `sdm ${running.command} is still running (job ${running.id}). A browser tab runs one command at a time.`
        : "Another command is starting.";
      throw new ApiError(409, message, running ? { job: running.id } : null);
    }
    starting = true;
    try {
      // A command that can read a playlist gets the Spotify login, if there is
      // one, whatever its form holds: Python decides whether the run needs it.
      const { commands } = await python.ready;
      const readsPlaylist = commands.some((c) => c.name === command && c.fields.some((f) => f.dest === "playlist"));
      const login = readsPlaylist ? await spotify.forRun() : null;
      const { argv, display } = await call<{ argv: string[]; display: string }>("prepare", {
        command,
        values,
        spotify: login !== null,
      });
      const job: Job = {
        id: String(jobs.length + 1),
        command,
        display,
        status: "running",
        exit_code: null,
        started: Date.now() / 1000,
        ended: null,
        cancel_requested: false,
        lines: [],
        first_line: 0,
        outputs: [],
      };
      jobs.push(job);
      python.send<RunResult & { io: { reads: number; bytes: number; ms: number } }>({
        type: "run",
        job: job.id,
        command,
        argv,
        spotify: login,
      }).then(
        (result) => {
          if (result.cancelled) {
            appendLine(job.id, ["err", "Nothing this run wrote was kept; earlier reports are as they were."]);
            finish(job, "cancelled", result.exit_code);
            return;
          }
          keepReports(result);
          job.outputs = result.outputs;
          if (job.cancel_requested) appendLine(job.id, ["err", "The command had finished before the cancel reached it; its reports are kept."]);
          finish(job, result.exit_code === 0 ? "succeeded" : "failed", result.exit_code);
          if (BLOCK_KNOB !== null) {
            const seconds = ((job.ended ?? 0) - job.started).toFixed(2);
            console.debug(`sdm io: job ${job.id} ${command} ${seconds}s ${JSON.stringify(result.io)}`);
          }
        },
        (e: unknown) => {
          if (job.status !== "running") return; // cancelled: already recorded
          appendLine(job.id, ["err", `error: ${e instanceof Error ? e.message : String(e)}`]);
          finish(job, "failed", null);
        },
      );
      return detail(job, 0);
    } finally {
      starting = false;
    }
  },

  // Python is interrupted, as Ctrl-C would, and the worker drops what the run
  // wrote; the run's reply says so. Signalled until it stops, because Pyodide
  // can miss a signal. Without cross-origin isolation Python cannot be
  // interrupted, and a command that has not stopped in CANCEL_GRACE_MS will not
  // be: either way the worker is ended and another started instead.
  cancelJob: async (id: string): Promise<JobDetail> => {
    const job = findJob(id);
    if (job.status === "running" && !job.cancel_requested) {
      job.cancel_requested = true;
      const current = python;
      if (current.interrupt(Number(job.id))) {
        const asked = Date.now();
        const timer = window.setInterval(() => {
          if (job.status !== "running" || python !== current) {
            window.clearInterval(timer);
          } else if (Date.now() - asked < CANCEL_GRACE_MS) {
            current.interrupt(Number(job.id));
          } else {
            window.clearInterval(timer);
            restart(job, "the command did not stop in time, so Python was restarted in this tab.");
          }
        }, RESIGNAL_MS);
      } else {
        restart(job, "Python was stopped and restarted in this tab.");
      }
    }
    return detail(job, 1e9);
  },

  // From the page's own copies: instant, even while a run has the worker busy.
  reports: async (): Promise<{ root: string; files: ReportFile[] }> => {
    const root = outRoot();
    const files = [...reports].map(([path, r]): ReportFile => {
      const rel = path.slice(root.length + 1);
      const slash = rel.lastIndexOf("/");
      return { rel, name: rel.slice(slash + 1), folder: slash >= 0 ? rel.slice(0, slash) : "", size: r.blob.size, mtime: r.mtime };
    });
    files.sort((a, b) => b.mtime - a.mtime);
    return { root, files };
  },
  table: (
    path: string,
    opts: { offset?: number; limit?: number; q?: string; sort?: number | null; desc?: boolean } = {},
  ): Promise<TablePage> =>
    call<TablePage>("table", { path, offset: opts.offset ?? 0, limit: opts.limit ?? 100, q: opts.q ?? "", sort: opts.sort ?? null, desc: !!opts.desc }),
  raw: async <T,>(path: string): Promise<T> => JSON.parse(await reportOrThrow(path).blob.text()) as T,
  fs: async (): Promise<never> => {
    throw new ApiError(501, "There is no filesystem to browse in a browser tab: choose a folder instead.");
  },
};

export const rawUrl = (path: string): string => {
  const report = reports.get(outPath(path));
  if (!report) return "#";
  report.url ??= URL.createObjectURL(report.blob);
  return report.url;
};

/** Unused here: the player asks `browser.audioSrc`, which can open a file lazily. */
export const audioUrl = (_path: string): string => "";

export const browser: BrowserHooks = {
  subscribeBoot(listener) {
    bootListeners.add(listener);
    listener(bootState);
    return () => void bootListeners.delete(listener);
  },
  canViewFolders: typeof window.showDirectoryPicker === "function",
  offline: () => info?.offline ?? [],

  async pick(mode, accept, onProgress, options) {
    if (mode === "dir") return pickFolder(onProgress, !!options?.fallback);
    const files = await chooseFiles({ directory: false, accept });
    if (!files?.length) return null;
    const current = python;
    await current.ready;
    const path = await current.send<string>({ type: "file", name: mountName(files[0].name), file: files[0] });
    return { path, summary: files[0].name };
  },

  isPlayable(path) {
    const found = mountFor(path);
    const lower = path.toLowerCase();
    if (!found || !info?.mount.audio_exts.some((ext) => lower.endsWith(ext))) return false;
    return found.mount.source.kind === "handle" || found.mount.source.files.has(found.rel);
  },

  async audioSrc(path) {
    const found = mountFor(path);
    if (!found) throw new Error("This file is not in a folder picked in this tab.");
    let file: File | undefined;
    if (found.mount.source.kind === "files") {
      file = found.mount.source.files.get(found.rel);
    } else {
      const parts = found.rel.split("/");
      let dir = found.mount.source.handle;
      for (const part of parts.slice(0, -1)) dir = await dir.getDirectoryHandle(part);
      file = await (await dir.getFileHandle(parts[parts.length - 1])).getFile();
    }
    if (!file) throw new Error("This file is not in the picked folder.");
    if (playing) URL.revokeObjectURL(playing);
    playing = URL.createObjectURL(file);
    return playing;
  },

  spotify: {
    subscribe: spotify.subscribe,
    setClientId: spotify.setClientId,
    async login() {
      const { spotify_scopes } = await python.ready;
      await spotify.login(spotify_scopes);
    },
    logout: spotify.logout,
    wouldForget() {
      const count = (n: number, what: string) => `${n} ${what}${n === 1 ? "" : "s"}`;
      const lost: string[] = [];
      if (jobs.some((j) => j.status === "running")) lost.push("the running command");
      if (mounts.size) lost.push(count(mounts.size, "picked folder"));
      if (reports.size) lost.push(count(reports.size, "report"));
      return lost.length ? lost.join(", ").replace(/, ([^,]*)$/, " and $1") : null;
    },
  },
};
