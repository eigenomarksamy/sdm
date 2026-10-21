import { useEffect, useState } from "react";
import { api, browser, type Command, type JobSummary, type ReportFile, type Session } from "../api";
import { PrivacyNote } from "../browser/ui";
import { StatusBadge } from "../components";
import { ago } from "../format";
import { href } from "../router";
import { viewLabel } from "./ReportPage";

export function Home({ commands, jobs, session }: { commands: Command[]; jobs: JobSummary[]; session: Session }) {
  const [reports, setReports] = useState<ReportFile[] | null>(null);
  useEffect(() => {
    api.reports().then((r) => setReports(r.files)).catch(() => setReports([]));
  }, []);

  return (
    <div className="page">
      <header className="page-head">
        <h1>Music library toolchain</h1>
        {browser ? (
          <>
            <PrivacyNote />
            <p className="muted">
              Not in the browser:{" "}
              {browser.offline().map((name, i) => (
                <span key={name}>
                  {i > 0 && ", "}
                  <code>{name}</code>
                </span>
              ))}
              , and Spotify links in <code>playlist-diff</code> (a CSV export works). They need fpcalc, ffmpeg or a
              Spotify login, so they run with sdm on your own machine.
            </p>
          </>
        ) : (
          <p className="muted">
            Every command from <code>sdm --help</code>, run on this machine. Reports land in{" "}
            <code>{session.out_root}</code>.
          </p>
        )}
      </header>

      <section className="cards">
        {commands.map((c) => (
          <a key={c.name} className="card" href={href(`/run/${c.name}`)}>
            <strong>{c.name}</strong>
            <span className="muted">{c.help}</span>
          </a>
        ))}
      </section>

      <div className="two-col">
        <section>
          <h2>Recent jobs</h2>
          {jobs.length === 0 ? (
            <p className="muted">Nothing run yet in this session.</p>
          ) : (
            <ul className="plain-list">
              {jobs.slice(0, 8).map((j) => (
                <li key={j.id}>
                  <a href={href(`/jobs/${j.id}`)}>
                    <StatusBadge status={j.status} cancelling={j.cancel_requested} /> {j.command}
                  </a>{" "}
                  <span className="muted">{ago(j.started)}</span>
                </li>
              ))}
            </ul>
          )}
        </section>
        <section>
          <h2>Latest reports</h2>
          {reports === null ? (
            <p className="muted">Loading…</p>
          ) : reports.length === 0 ? (
            <p className="muted">No reports yet.</p>
          ) : (
            <ul className="plain-list">
              {reports.slice(0, 8).map((r) => (
                <li key={r.rel}>
                  <a href={href("/report", { path: r.rel })}>{r.rel}</a>{" "}
                  <span className="muted">
                    {viewLabel(r.rel)} · {ago(r.mtime)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </div>
  );
}
