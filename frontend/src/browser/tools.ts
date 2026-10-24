// The audio tools the browser build runs: fpcalc, ffprobe and sdm_ffmpeg,
// WebAssembly builds of the same releases sdm runs natively (wasm/build.sh).
//
// Natively they are processes, started by `core.tools.run`. Here Python calls
// `runTool` through `sdm_tools` (registered by worker.ts) with the same argv,
// and gets the same three things back: the exit code, stdout (streamed while
// the tool runs, or collected) and stderr.
//
// A fresh instance per run, as a process is fresh per run: these programs keep
// their state in globals, and calling main twice in one instance is not
// something they are written for. Compiling is the expensive part and happens
// once (`loadTool`); instantiating the compiled module takes ~2 ms. It is
// synchronous because Python's call is: the modules are built with
// WASM_ASYNC_COMPILATION=0, so the instance is ready when `create` returns,
// though `create` returns a promise.
//
// Self-contained (no imports), so the Node test harness can load it too.

/** The parts of an Emscripten FS used here. */
export interface ToolFs {
  registerDevice(dev: number, ops: DeviceOps): void;
  makedev(major: number, minor: number): number;
  mkdev(path: string, dev: number): void;
  open(path: string, flags: string): { fd: number };
  close(stream: unknown): void;
  getStream(fd: number): unknown;
  mkdirTree(path: string): void;
  mount(type: unknown, options: unknown, mountpoint: string): void;
  writeFile(path: string, data: Uint8Array): void;
  filesystems: { WORKERFS: unknown };
}

interface DeviceOps {
  open(): void;
  close(): void;
  read(): number;
  write(stream: unknown, buffer: Uint8Array, offset: number, length: number): number;
}

interface ToolModule {
  FS?: ToolFs;
  callMain?: (args: string[]) => number | undefined;
  [key: string]: unknown;
}

export interface Tool {
  name: string;
  create: (module: ToolModule) => unknown;
  wasm: WebAssembly.Module;
}

export interface ToolResult {
  code: number;
  stdout: Uint8Array;
  stderr: Uint8Array;
}

/**
 * Give a tool instance the file at `path`, at the same path. Python names
 * picked files by their paths in its own filesystem; each instance has its own.
 */
export type Provide = (fs: ToolFs, path: string) => void;

/** The module file behind each name `core.tools` runs. */
export const TOOL_FILES: Record<string, string> = { fpcalc: "fpcalc", ffprobe: "ffprobe", ffmpeg: "sdm_ffmpeg" };

/** stdout is handed to Python in pieces of about this size, not per write: each hand-over crosses into Python. */
const HANDOVER_BYTES = 256 * 1024;

/** Fetch and compile one tool, from `dir` (the manifest's `tools`, as a URL). */
export async function loadTool(dir: string, name: string): Promise<Tool> {
  const url = new URL(TOOL_FILES[name], dir).href;
  const [script, wasm] = await Promise.all([
    import(/* @vite-ignore */ `${url}.mjs`) as Promise<{ default: Tool["create"] }>,
    WebAssembly.compileStreaming(fetch(`${url}.wasm`)),
  ]);
  return { name, create: script.default, wasm };
}

export function runTool(tool: Tool, args: string[], onStdout: ((chunk: Uint8Array) => void) | null, provide: Provide): ToolResult {
  let code = 0;
  const module: ToolModule = {
    wasmModule: tool.wasm, // reused by the patched glue; see wasm/build.sh
    noInitialRun: true,
    onExit: (status: number) => {
      code = status;
    },
    print: () => undefined,
    printErr: () => undefined,
  };
  void tool.create(module);
  const fs = module.FS;
  if (!fs || !module.callMain) throw new Error(`${tool.name} did not start synchronously`);

  const stdout = new Sink(onStdout);
  const stderr = new Sink(null);
  attach(fs, 1, "/dev/sdm-stdout", 64, stdout);
  attach(fs, 2, "/dev/sdm-stderr", 65, stderr);
  for (const arg of args) if (arg.startsWith("/")) provide(fs, arg);

  try {
    const returned = module.callMain(args);
    if (typeof returned === "number") code = returned;
  } catch (e) {
    // exit() inside the program, which `onExit` has already reported. Anything
    // else - a cancel raised by Python's stdout callback - goes back to Python.
    if (!(typeof e === "object" && e !== null && (e as { name?: string }).name === "ExitStatus")) throw e;
  }
  stdout.flush();
  return { code, stdout: stdout.collected(), stderr: stderr.collected() };
}

/** Replace standard stream `fd` with a device that writes into `sink`. */
function attach(fs: ToolFs, fd: number, path: string, major: number, sink: Sink): void {
  const dev = fs.makedev(major, 0);
  fs.registerDevice(dev, {
    open: () => undefined,
    close: () => undefined,
    read: () => 0,
    write: (_stream, buffer, offset, length) => {
      sink.write(buffer.subarray(offset, offset + length));
      return length;
    },
  });
  fs.mkdev(path, dev);
  fs.close(fs.getStream(fd));
  // The lowest free descriptor, which is the one just closed.
  if (fs.open(path, "w").fd !== fd) throw new Error(`could not attach ${path} as fd ${fd}`);
}

/** A stream's bytes: handed over in pieces while the tool runs, or kept until it ends. */
class Sink {
  private chunks: Uint8Array[] = [];
  private size = 0;
  private onChunk: ((chunk: Uint8Array) => void) | null;

  constructor(onChunk: ((chunk: Uint8Array) => void) | null) {
    this.onChunk = onChunk;
  }

  write(bytes: Uint8Array): void {
    this.chunks.push(bytes.slice()); // the tool reuses its buffer
    this.size += bytes.length;
    if (this.onChunk && this.size >= HANDOVER_BYTES) this.flush();
  }

  flush(): void {
    if (!this.onChunk || !this.size) return;
    const piece = this.join();
    this.chunks = [];
    this.size = 0;
    this.onChunk(piece);
  }

  collected(): Uint8Array {
    return this.onChunk ? new Uint8Array(0) : this.join();
  }

  private join(): Uint8Array {
    const all = new Uint8Array(this.size);
    let at = 0;
    for (const chunk of this.chunks) {
      all.set(chunk, at);
      at += chunk.length;
    }
    return all;
  }
}
