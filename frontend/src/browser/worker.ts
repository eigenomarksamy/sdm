// The browser build's Python: Pyodide in a module worker, one per tab.
//
// The page (browser/api.ts) answers the same calls `sdm web`'s server does, and
// anything that needs Python comes here. Messages are handled strictly one at a
// time — Pyodide is single-threaded, and a run blocks this worker until it ends.
// Cancelling therefore cannot be a message: the page writes to memory shared
// with this worker, which Python polls (protocol.ts), or, where it cannot,
// terminates the worker and starts another. That is why every report is also
// carried back to the page.
//
// Module, not classic: Pyodide 314 refuses classic workers outright.
import type { PyodideAPI } from "pyodide";
import type { JobOutput } from "../api";
import { keepForMount, mountName, ntfsCompare } from "./files";
import { CANCEL_JOB, SIGNAL } from "./protocol";
import type { BootInfo, FromWorker, Manifest, MountedFolder, OutFile, RunResult, Staged, ToWorker } from "./protocol";

/**
 * Bytes per cached block when a picked file is read, and blocks kept per open
 * file. Every WORKERFS read is a blob slice plus a synchronous FileReaderSync
 * round trip to the browser process, ~0.7 ms however few bytes it returns, and
 * a tag reader makes several small reads near the start and end of each file.
 * Serving those from a few cached blocks turns most of them into a copy. The
 * bytes are the file's own either way, so results cannot change.
 *
 * Measured on the reference USB in Edge (`catalog --missing-metadata`): no
 * cache 33-35s; 64 KiB 18-19s; 256 KiB 18s; 1 MiB 28s, because it reads 5.9 GB
 * to answer reads mutagen meant to be small. 64 KiB and 256 KiB are within
 * noise of each other; 64 KiB reads a third fewer bytes doing it.
 */
const BLOCK_SIZE = 64 * 1024;
const KEEP_BLOCKS = 4;

declare const FileReaderSync: { new (): { readAsArrayBuffer(blob: Blob): ArrayBuffer } };

interface Scope {
  postMessage(message: FromWorker, transfer?: Transferable[]): void;
  onmessage: ((event: MessageEvent<ToWorker>) => void) | null;
}

// The parts of Emscripten's FS used here, typed narrowly enough to be checked.
interface Stat {
  mode: number;
  size: number;
  mtime: Date | number;
}
interface WorkerFsStream {
  node: { contents: Blob };
  blocks?: Map<number, Uint8Array>;
}
interface WorkerFs {
  stream_ops: { read(stream: WorkerFsStream, buffer: Uint8Array, offset: number, length: number, position: number): number };
  node_ops: { readdir(node: { contents: Record<string, unknown> }): string[] };
}
interface EmFs {
  mkdirTree(path: string): void;
  mount(type: unknown, options: unknown, mountpoint: string): void;
  unmount(mountpoint: string): void;
  readdir(path: string): string[];
  stat(path: string): Stat;
  isDir(mode: number): boolean;
  analyzePath(path: string): { exists: boolean };
  readFile(path: string): Uint8Array;
  writeFile(path: string, data: Uint8Array): void;
  utime(path: string, atime: number, mtime: number): void;
  rename(from: string, to: string): void;
  unlink(path: string): void;
  rmdir(path: string): void;
  filesystems: { WORKERFS: WorkerFs };
}

const scope = self as unknown as Scope;
const post = (message: FromWorker, transfer: Transferable[] = []) => scope.postMessage(message, transfer);

let py: PyodideAPI;
let fs: EmFs;
let info: BootInfo;
let python: (name: string, args: string) => string;
let staged: Staged[] = [];
const mounted = new Set<string>();
/** The cancel channel (protocol.ts); null when the page is not cross-origin isolated. */
let control: Int32Array | null = null;

// The run in progress: where its output lines go, and the reports it announced.
let job: string | null = null;
let wrote: string[] = [];
const io = { reads: 0, bytes: 0, ms: 0 };

class CallError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

let queue: Promise<void> = Promise.resolve();
scope.onmessage = ({ data }) => {
  queue = queue.then(() => handle(data));
};

async function handle(message: ToWorker): Promise<void> {
  try {
    const [data, transfer] = await dispatch(message);
    post({ type: "reply", id: message.id, ok: true, data }, transfer);
  } catch (e) {
    const status = e instanceof CallError ? e.status : 500;
    post({ type: "reply", id: message.id, ok: false, status, error: e instanceof Error ? e.message : String(e) });
  }
}

async function dispatch(message: ToWorker): Promise<[unknown, Transferable[]]> {
  switch (message.type) {
    case "init":
      control = message.control;
      return [await boot(message.base, message.blockSize), []];
    case "call":
      return [call(message.name, message.args), []];
    case "run": {
      const result = run(message.job, message.command, message.argv);
      return [result, result.changed.map((f) => f.data)];
    }
    case "stage":
      staged.push(...message.files);
      return [staged.length, []];
    case "mount": {
      const files = message.handle ? await collect(message.handle, message.id) : staged;
      staged = [];
      return [mount(mountName(message.name), files), []];
    }
    case "csv":
      return [await writeCsv(message.name, message.file), []];
    case "restore":
      for (const file of message.files) await restore(file.path, file.mtime, file.data);
      return [message.files.length, []];
  }
}

// --- boot ------------------------------------------------------------------------

async function boot(base: string, blockSize: number | null): Promise<BootInfo> {
  const manifest = (await (await fetch(new URL("python.json", base))).json()) as Manifest;
  const total = Object.values(manifest.bytes).reduce((a, b) => a + b, 0);
  let loaded = 0;
  let step = "Downloading Python";
  const report = () => post({ type: "boot", step, loaded, total });
  const restoreFetch = countDownloads(manifest.bytes, (n) => {
    loaded += n;
    report();
  });
  report();

  const indexURL = new URL(manifest.pyodide, base).href;
  const { loadPyodide } = (await import(/* @vite-ignore */ `${indexURL}pyodide.mjs`)) as typeof import("pyodide");
  py = await loadPyodide({ indexURL, packageBaseUrl: indexURL, lockFileContents: JSON.stringify(manifest.lock) });
  fs = py.FS as unknown as EmFs;
  py.setStdout({ batched: (text: string) => line("out", text) });
  py.setStderr({ batched: (text: string) => line("err", text) });
  const quiet = { messageCallback: () => undefined };
  step = "Installing packages";
  report();
  await py.loadPackage(manifest.packages, quiet);
  await py.loadPackage(manifest.wheels.map((w) => new URL(`wheels/${w}`, base).href), quiet);
  restoreFetch();

  step = "Starting sdm";
  report();
  python = py.pyimport("sdm.browser").call;
  info = call<BootInfo>("boot", {});
  patchWorkerFs(blockSize ?? BLOCK_SIZE);
  // After boot, which installs the handler that keeps a cancel inside a run.
  if (control) py.setInterruptBuffer(control);
  return info;
}

/**
 * Count the bytes of every download the boot makes, for the progress bar.
 * Pyodide fetches the runtime, the standard library and every package with
 * `fetch`, so wrapping it sees them all; the body is passed on unchanged.
 */
function countDownloads(sizes: Record<string, number>, onBytes: (n: number) => void): () => void {
  const original = globalThis.fetch;
  globalThis.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
    const response = await original(input, init);
    const url = new URL(input instanceof Request ? input.url : String(input), self.location.href);
    if (!(url.pathname in sizes) || !response.body) return response;
    const counted = response.body.pipeThrough(
      new TransformStream<Uint8Array, Uint8Array>({
        transform(chunk, controller) {
          onBytes(chunk.byteLength);
          controller.enqueue(chunk);
        },
      }),
    );
    return new Response(counted, { status: response.status, statusText: response.statusText, headers: response.headers });
  };
  return () => {
    globalThis.fetch = original;
  };
}

function call<T>(name: string, args: Record<string, unknown>): T {
  const reply = JSON.parse(python(name, JSON.stringify(args))) as
    | { ok: true; data: T }
    | { ok: false; status: number; error: string };
  if (!reply.ok) throw new CallError(reply.status, reply.error);
  return reply.data;
}

function line(stream: "out" | "err", text: string): void {
  if (job === null) {
    // Outside a run: import-time warnings and the like. Not the page's business.
    console.debug(`[python ${stream}] ${text}`);
    return;
  }
  post({ type: "line", job, stream, text });
  const match = stream === "out" ? /^wrote (.+)$/.exec(text) : null;
  if (match) wrote.push(match[1].trim());
}

// --- runs -------------------------------------------------------------------------

/**
 * Run one command. A cancelled run leaves the output root exactly as it found
 * it, half-written reports included: the run writes into an empty output root
 * while the earlier reports wait beside it, and `putBack` restores them after,
 * dropping or keeping what the run wrote. Renames, no copies. No command reads
 * its own earlier reports, so none can tell. A run that fails rather than being
 * cancelled keeps what it wrote, as a failed run on disk would.
 */
function run(id: string, command: string, argv: string[]): RunResult & { io: typeof io } {
  // A cancel that came after the last run ended may still be in the buffer, and
  // is not for this run. Cleared before CANCEL_JOB is read, which the page writes first.
  if (control) Atomics.store(control, SIGNAL, 0);
  if (cancelled(id)) return { exit_code: null, cancelled: true, outputs: [], changed: [], io: { ...io } };

  const root = info.out_root;
  const earlier = `${root}.earlier`;
  fs.rename(root, earlier);
  fs.mkdirTree(root);
  let keep = false;
  try {
    const started = Date.now() / 1000;
    job = id;
    wrote = [];
    Object.assign(io, { reads: 0, bytes: 0, ms: 0 });
    let exitCode: number;
    try {
      exitCode = call<number>("run", { argv });
    } finally {
      job = null;
    }
    // Decided here, not by how Python ended: a cancel that arrives as the command
    // finishes still cancels it, and the page waits for this answer to say which.
    if (cancelled(id)) return { exit_code: exitCode, cancelled: true, outputs: [], changed: [], io: { ...io } };

    // Before the earlier reports are back, so that only this run's are found.
    const outputs = call<JobOutput[]>("outputs", { command, started, wrote });
    // Everything the run wrote goes back to the page, which keeps it: reports must
    // outlive a restart, and the page lists them while the next run blocks this worker.
    const changed: OutFile[] = files(root).map((path) => ({
      path,
      mtime: toMs(fs.stat(path).mtime) / 1000,
      data: fs.readFile(path).buffer as ArrayBuffer,
    }));
    keep = true;
    return { exit_code: exitCode, cancelled: false, outputs, changed, io: { ...io } };
  } finally {
    putBack(root, earlier, keep);
  }
}

/** Whether the page has asked to cancel job `id`. */
function cancelled(id: string): boolean {
  return control !== null && Atomics.load(control, CANCEL_JOB) === Number(id);
}

/**
 * After a run: the earlier reports back under `root`. With `keep`, those the run
 * did not rewrite join what it wrote; without, what it wrote is removed first.
 */
function putBack(root: string, earlier: string, keep: boolean): void {
  if (!keep) {
    removeTree(root);
    fs.rename(earlier, root);
    return;
  }
  for (const path of files(earlier)) {
    const target = root + path.slice(earlier.length);
    if (fs.analyzePath(target).exists) continue; // rewritten by this run
    fs.mkdirTree(target.slice(0, target.lastIndexOf("/")));
    fs.rename(path, target);
  }
  removeTree(earlier);
}

/** Every file under `root`, by path. */
function files(root: string): string[] {
  const found: string[] = [];
  const walk = (dir: string) => {
    for (const name of fs.readdir(dir)) {
      if (name === "." || name === "..") continue;
      const path = `${dir}/${name}`;
      if (fs.isDir(fs.stat(path).mode)) walk(path);
      else found.push(path);
    }
  };
  walk(root);
  return found;
}

function removeTree(dir: string): void {
  for (const name of fs.readdir(dir)) {
    if (name === "." || name === "..") continue;
    const path = `${dir}/${name}`;
    if (fs.isDir(fs.stat(path).mode)) removeTree(path);
    else fs.unlink(path);
  }
  fs.rmdir(dir);
}

function toMs(time: Date | number): number {
  return time instanceof Date ? time.getTime() : Number(time);
}

async function restore(path: string, mtime: number, data: Blob): Promise<void> {
  fs.mkdirTree(path.slice(0, path.lastIndexOf("/")));
  fs.writeFile(path, new Uint8Array(await data.arrayBuffer()));
  fs.utime(path, mtime * 1000, mtime * 1000);
}

// --- picked folders -------------------------------------------------------------------

/**
 * Walk a directory handle (the File System Access picker) and keep what a
 * command reads. The handle crosses from the page without cloning anything;
 * the `File`s are fetched here, a directory's worth at a time.
 */
async function collect(root: FileSystemDirectoryHandle, id: number): Promise<Staged[]> {
  const kept: Staged[] = [];
  let seen = 0;
  const walk = async (dir: FileSystemDirectoryHandle, prefix: string): Promise<void> => {
    const files: Promise<void>[] = [];
    for await (const entry of dir.values()) {
      const rel = prefix + entry.name;
      if (++seen % 500 === 0) post({ type: "progress", id, seen, kept: kept.length + files.length });
      if (entry.kind === "directory") {
        await walk(entry as FileSystemDirectoryHandle, `${rel}/`);
      } else if (keepForMount(`${root.name}/${rel}`, info.mount)) {
        files.push((entry as FileSystemFileHandle).getFile().then((file) => void kept.push({ rel, file })));
      }
    }
    await Promise.all(files);
  };
  await walk(root, "");
  post({ type: "progress", id, seen, kept: kept.length });
  return kept;
}

function mount(name: string, files: Staged[]): MountedFolder {
  const path = `${info.music_root}/${name}`;
  if (mounted.has(path)) fs.unmount(path);
  fs.mkdirTree(path);
  fs.mount(fs.filesystems.WORKERFS, { blobs: files.map((f) => ({ name: f.rel, data: f.file })) }, path);
  mounted.add(path);
  const audio = files.filter((f) => info.mount.audio_exts.some((ext) => f.rel.toLowerCase().endsWith(ext))).length;
  return { path, files: files.length, audio, analysis: files.length - audio };
}

async function writeCsv(name: string, file: File): Promise<string> {
  const path = `${info.playlist_root}/${name.replace(/[\\/]/g, "_")}`;
  fs.mkdirTree(info.playlist_root);
  fs.writeFile(path, new Uint8Array(await file.arrayBuffer()));
  return path;
}

/**
 * Two changes to WORKERFS, the read-only filesystem picked files are mounted
 * with. Neither can change what a command reads, only the order and the cost.
 *
 * `readdir` lists in NTFS order. WORKERFS keeps a directory's entries in a
 * plain object, and an object lists number-like keys first in numeric order
 * ("1977" before "!!!"), whatever order they were added in — so sorting the
 * files before mounting could not fix the order. Sorting here does.
 *
 * `read` goes through a few cached blocks per open file; see BLOCK_SIZE.
 * A block size of 0 turns the cache off (`?block=0` on the page), for measuring.
 */
function patchWorkerFs(blockSize: number): void {
  const workerfs = fs.filesystems.WORKERFS;
  workerfs.node_ops.readdir = (node) => [".", "..", ...Object.keys(node.contents).sort(ntfsCompare)];

  const reader = new FileReaderSync();
  const slice = (blob: Blob, start: number, end: number) => {
    const t = performance.now();
    const bytes = new Uint8Array(reader.readAsArrayBuffer(blob.slice(start, end)));
    io.reads++;
    io.bytes += bytes.length;
    io.ms += performance.now() - t;
    return bytes;
  };

  workerfs.stream_ops.read = (stream, buffer, offset, length, position) => {
    const blob = stream.node.contents;
    const end = Math.min(position + length, blob.size);
    if (position >= end) return 0;
    if (!blockSize) {
      buffer.set(slice(blob, position, end), offset);
      return end - position;
    }

    const blocks = (stream.blocks ??= new Map());
    const first = Math.floor(position / blockSize);
    const last = Math.floor((end - 1) / blockSize);
    // Every block this read needs that is not cached, fetched in one slice.
    let lo = -1;
    let hi = -1;
    for (let i = first; i <= last; i++) {
      if (!blocks.has(i)) {
        if (lo < 0) lo = i;
        hi = i;
      }
    }
    if (lo >= 0) {
      const bytes = slice(blob, lo * blockSize, Math.min((hi + 1) * blockSize, blob.size));
      for (let i = lo; i <= hi; i++) {
        blocks.delete(i);
        blocks.set(i, bytes.subarray((i - lo) * blockSize, (i - lo + 1) * blockSize));
      }
    }

    let written = 0;
    for (let i = first; i <= last; i++) {
      const block = blocks.get(i)!;
      blocks.delete(i); // re-inserted last: the Map's order is the recency order
      blocks.set(i, block);
      const from = Math.max(position - i * blockSize, 0);
      const to = Math.min(end - i * blockSize, block.length);
      buffer.set(block.subarray(from, to), offset + written);
      written += to - from;
    }
    while (blocks.size > KEEP_BLOCKS) blocks.delete(blocks.keys().next().value!);
    return written;
  };
}
