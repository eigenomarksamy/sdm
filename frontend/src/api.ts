// The server's JSON API, typed. Shapes mirror src/sdm/web/*.py; when one
// changes there, change it here.

export interface Session {
  version: string;
  out_root: string;
  tmp_root: string;
  cwd: string;
  sep: string;
  spotify_client_id: boolean;
}

export type FieldKind = "flag" | "optional_value" | "choice" | "integer" | "number" | "text";

export interface Field {
  dest: string;
  flag: string | null;
  label: string;
  positional: boolean;
  kind: FieldKind;
  required: boolean;
  default: string | number | boolean | null;
  help: string;
  metavar: string | null;
  choices: string[] | null;
  path: "dir" | "file" | null;
  accept: string[];
}

export interface Command {
  name: string;
  help: string;
  description: string;
  fields: Field[];
}

export type JobStatus = "running" | "succeeded" | "failed" | "cancelled";

export interface JobSummary {
  id: string;
  command: string;
  display: string;
  status: JobStatus;
  exit_code: number | null;
  started: number;
  ended: number | null;
  cancel_requested: boolean;
}

export type LogLine = [stream: "out" | "err", text: string];

export interface JobOutput {
  path: string;
  rel: string | null;
  exists: boolean;
}

export interface JobDetail extends JobSummary {
  lines: LogLine[];
  next: number;
  dropped: number;
  outputs: JobOutput[];
}

export interface ReportFile {
  rel: string;
  name: string;
  folder: string;
  size: number;
  mtime: number;
}

export interface TablePage {
  header: string[];
  rows: string[][];
  total: number;
  matched: number | null;
  offset: number;
  mode: "memory" | "stream";
}

export interface FsEntry {
  name: string;
  path: string;
  dir: boolean;
}

export interface FsListing {
  path: string;
  parent: string | null;
  entries: FsEntry[];
}

export type FormValue = string | boolean | null;
export type FormValues = Record<string, FormValue>;

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public body: Record<string, unknown> | null = null,
  ) {
    super(message);
  }
}

async function request<T>(method: "GET" | "POST", url: string, body?: unknown): Promise<T> {
  const res = await fetch(url, {
    method,
    credentials: "same-origin",
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await res.text();
  let data: unknown = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    // Not JSON: a proxy error page, say. Reported by status below.
  }
  if (!res.ok) {
    const obj = (data && typeof data === "object" ? data : null) as Record<string, unknown> | null;
    const message = typeof obj?.error === "string" ? obj.error : `${res.status} ${res.statusText}`;
    throw new ApiError(res.status, message, obj);
  }
  return data as T;
}

function qs(params: Record<string, string | number | boolean | null | undefined>): string {
  const search = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === null || v === undefined || v === "" || v === false) continue;
    search.set(k, v === true ? "1" : String(v));
  }
  const s = search.toString();
  return s ? `?${s}` : "";
}

export const api = {
  session: () => request<Session>("GET", "/api/session"),
  commands: () => request<Command[]>("GET", "/api/commands"),
  jobs: () => request<JobSummary[]>("GET", "/api/jobs"),
  job: (id: string, since = 0) => request<JobDetail>("GET", `/api/jobs/${id}${qs({ since })}`),
  startJob: (command: string, values: FormValues) =>
    request<JobDetail>("POST", "/api/jobs", { command, values }),
  // `since` far past the end: the answer is the status, not the log again.
  cancelJob: (id: string) => request<JobDetail>("POST", `/api/jobs/${id}/cancel${qs({ since: 1e9 })}`, {}),
  reports: () => request<{ root: string; files: ReportFile[] }>("GET", "/api/reports"),
  table: (
    path: string,
    opts: { offset?: number; limit?: number; q?: string; sort?: number | null; desc?: boolean } = {},
  ) =>
    request<TablePage>(
      "GET",
      `/api/reports/table${qs({ path, offset: opts.offset, limit: opts.limit, q: opts.q, sort: opts.sort ?? undefined, desc: opts.desc })}`,
    ),
  raw: async <T,>(path: string): Promise<T> => request<T>("GET", rawUrl(path)),
  fs: (path: string, files: boolean, accept: string[]) =>
    request<FsListing>("GET", `/api/fs${qs({ path, files, accept: accept.join(",") })}`),
};

export const rawUrl = (path: string) => `/api/reports/raw${qs({ path })}`;
export const audioUrl = (path: string) => `/api/audio${qs({ path })}`;

// --- the browser build --------------------------------------------------------
//
// The browser build (sdm.eigenomar.com) has no server: `npm run build:browser`
// swaps this module for src/browser/api.ts, which answers every call above from
// Python running in a worker. What a page needs only there is below, and
// `browser` is null in this build, so a shared component can ask which it is in.

export interface BootState {
  /** What is happening, for the screen shown while Python starts. */
  step: string;
  /** Bytes of the runtime and packages downloaded so far, and in all. */
  loaded: number;
  total: number;
  error: string | null;
}

export interface PickProgress {
  text: string;
  done?: number;
  total?: number;
}

export interface BrowserHooks {
  subscribeBoot(listener: (state: BootState) => void): () => void;
  /** The File System Access picker, which asks to view a folder rather than to upload it. */
  canViewFolders: boolean;
  /** Commands that need sdm on a real machine, by name. Known once Python has started. */
  offline(): string[];
  /**
   * Ask for a folder (or a file), mount what the commands read, and resolve to
   * its path — null if the visitor closed the picker. Call it from a click:
   * browsers open pickers only in answer to one. `fallback` forces the
   * `<input webkitdirectory>` picker even where the other exists.
   */
  pick(
    mode: "dir" | "file",
    accept: string[],
    onProgress: (progress: PickProgress) => void,
    options?: { fallback?: boolean },
  ): Promise<{ path: string; summary: string } | null>;
  /** An audio file inside a picked folder: what can be played. */
  isPlayable(path: string): boolean;
  /** A URL for the player. Async, because a folder handle opens files lazily. */
  audioSrc(path: string): Promise<string>;
}

export const browser: BrowserHooks | null = null;
