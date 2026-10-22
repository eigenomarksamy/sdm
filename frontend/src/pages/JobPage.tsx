import { memo, useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { api, browser, type JobDetail, type JobOutput, type LogLine } from "../api";
import { CopyButton, ErrorBox, StatusBadge } from "../components";
import { elapsed, plural } from "../format";
import { href } from "../router";
import { viewLabel } from "./ReportPage";

const POLL_MS = 700;

/**
 * One run: its live log, a cancel button, and links into what it wrote.
 *
 * The log arrives in chunks (whatever was new since the last poll) and each
 * chunk renders once, memoized, so a 9-minute duplicate scan's thousands of
 * lines do not re-render on every poll.
 */
export function JobPage({ id, onChange }: { id: string; onChange: () => void }) {
  const [job, setJob] = useState<JobDetail | null>(null);
  const [chunks, setChunks] = useState<LogLine[][]>([]);
  const [error, setError] = useState<unknown>(null);
  const [, setTick] = useState(0);
  const next = useRef(0);
  const dropped = useRef(0);
  const logRef = useRef<HTMLDivElement>(null);
  const stick = useRef(true);
  const status = useRef<string | null>(null);

  useEffect(() => {
    let stopped = false;
    let timer = 0;
    const poll = async () => {
      try {
        const detail = await api.job(id, next.current);
        if (stopped) return;
        dropped.current += detail.dropped;
        next.current = detail.next;
        if (detail.lines.length) setChunks((prev) => [...prev, detail.lines]);
        setJob(detail);
        if (status.current !== detail.status) {
          if (status.current !== null) onChange();
          status.current = detail.status;
        }
        if (detail.status === "running") timer = window.setTimeout(poll, POLL_MS);
      } catch (e) {
        if (!stopped) setError(e);
      }
    };
    void poll();
    return () => {
      stopped = true;
      window.clearTimeout(timer);
    };
  }, [id, onChange]);

  // A ticking clock while it runs.
  useEffect(() => {
    if (job?.status !== "running") return;
    const t = window.setInterval(() => setTick((n) => n + 1), 1000);
    return () => window.clearInterval(t);
  }, [job?.status]);

  // Follow the log's tail unless the reader has scrolled up to look at something.
  useLayoutEffect(() => {
    const el = logRef.current;
    if (el && stick.current) el.scrollTop = el.scrollHeight;
  }, [chunks]);

  if (error) return <ErrorBox error={error} />;
  if (!job) return <div className="muted">Loading…</div>;

  const progress = job.status === "running" ? lastProgress(chunks) : null;
  const lineCount = chunks.reduce((n, c) => n + c.length, 0);

  return (
    <div className="page">
      <header className="page-head">
        <h1>
          Job {job.id} <StatusBadge status={job.status} cancelling={job.cancel_requested} />
        </h1>
        <div className="command-line">
          <code>{job.display}</code>
          <CopyButton text={job.display} />
        </div>
        <p className="muted">
          {new Date(job.started * 1000).toLocaleString()} · {elapsed(job.started, job.ended)}
          {job.exit_code !== null && ` · exit code ${job.exit_code}`}
        </p>
        <div className="form-actions">
          {job.status === "running" && (
            <button
              className="danger"
              disabled={job.cancel_requested}
              onClick={async () => {
                const what = browser
                  ? "Nothing it has written is kept; reports from earlier runs stay as they were."
                  : "The run stops; nothing it has already written is undone.";
                if (!window.confirm(`Cancel sdm ${job.command}? ${what}`)) return;
                try {
                  await api.cancelJob(job.id);
                  setJob({ ...job, cancel_requested: true }); // the poll picks up the rest
                } catch (e) {
                  setError(e);
                }
              }}
            >
              {job.cancel_requested ? "Cancelling…" : "Cancel"}
            </button>
          )}
          <a className="button ghost" href={href(`/run/${job.command}`)}>
            {job.status === "running" ? "Back to the form" : "Run again"}
          </a>
        </div>
      </header>

      {progress && (
        <div className="progress" title={progress.text}>
          <div className="progress-bar" style={{ width: `${(100 * progress.done) / progress.total}%` }} />
          <span>
            {progress.text} ({Math.floor((100 * progress.done) / progress.total)}%)
          </span>
        </div>
      )}

      {job.status !== "running" && <Outputs outputs={job.outputs} />}

      <section>
        <h2>
          Output <span className="muted">{plural(lineCount, "line")}</span>
        </h2>
        <div
          className="log"
          ref={logRef}
          onScroll={(e) => {
            const el = e.currentTarget;
            stick.current = el.scrollTop + el.clientHeight >= el.scrollHeight - 24;
          }}
        >
          {dropped.current > 0 && <div className="log-note">… {plural(dropped.current, "earlier line")} not kept</div>}
          {chunks.map((chunk, i) => (
            <LogChunk key={i} lines={chunk} />
          ))}
          {job.status === "running" && <div className="log-note">running…</div>}
          {job.status !== "running" && lineCount === 0 && <div className="log-note">(no output)</div>}
        </div>
      </section>
    </div>
  );
}

function Outputs({ outputs }: { outputs: JobOutput[] }) {
  if (outputs.length === 0) return null;
  return (
    <section>
      <h2>Wrote</h2>
      <ul className="plain-list">
        {outputs.map((o) => (
          <li key={o.path}>
            {o.exists ? (
              <a href={href("/report", { path: o.rel ?? o.path })}>{o.rel ?? o.path}</a>
            ) : (
              <span className="muted">{o.path} (gone)</span>
            )}{" "}
            {o.exists && <span className="muted">{viewLabel(o.rel ?? o.path)}</span>}
          </li>
        ))}
      </ul>
    </section>
  );
}

const LogChunk = memo(function LogChunk({ lines }: { lines: LogLine[] }) {
  return (
    <>
      {lines.map(([stream, text], i) => (
        <div key={i} className={`log-line ${stream === "err" ? "err" : ""} ${/^error\b/i.test(text) ? "fatal" : ""}`}>
          {linkify(text)}
        </div>
      ))}
    </>
  );
});

/** URLs in the log are links: the Spotify login prints the one to open. */
function linkify(text: string): ReactNode {
  const parts = text.split(/(https?:\/\/[^\s"']+)/g);
  if (parts.length === 1) return text || " ";
  return parts.map((part, i) =>
    i % 2 === 1 ? (
      <a key={i} href={part} target="_blank" rel="noreferrer">
        {part}
      </a>
    ) : (
      part
    ),
  );
}

/**
 * The most recent "N/M" in the log, as progress. The commands do not report
 * progress in a structured way, but those that know a total print it like
 * this (`fingerprint: 1250/64272 pair(s) compared`).
 */
function lastProgress(chunks: LogLine[][]): { done: number; total: number; text: string } | null {
  for (let c = chunks.length - 1, seen = 0; c >= 0 && seen < 40; c--) {
    const chunk = chunks[c];
    for (let i = chunk.length - 1; i >= 0 && seen < 40; i--, seen++) {
      const m = /(\d[\d,]*)\s*\/\s*(\d[\d,]*)/.exec(chunk[i][1]);
      if (m) {
        const done = Number(m[1].replace(/,/g, ""));
        const total = Number(m[2].replace(/,/g, ""));
        if (total > 0 && done <= total) return { done, total, text: chunk[i][1].trim() };
      }
    }
  }
  return null;
}
