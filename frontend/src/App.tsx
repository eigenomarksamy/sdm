import { useCallback, useEffect, useState } from "react";
import { api, ApiError, type Command, type JobSummary, type Session } from "./api";
import { ErrorBox } from "./components";
import { CommandPage } from "./pages/CommandPage";
import { Home } from "./pages/Home";
import { JobPage } from "./pages/JobPage";
import { JobsPage } from "./pages/JobsPage";
import { ReportPage } from "./pages/ReportPage";
import { ReportsPage } from "./pages/ReportsPage";
import { href, useRoute } from "./router";

/** How often the sidebar refreshes the job list, which is what lights up a running job. */
const JOBS_POLL_MS = 2500;

export function App() {
  const route = useRoute();
  const [session, setSession] = useState<Session | null>(null);
  const [commands, setCommands] = useState<Command[]>([]);
  const [jobs, setJobs] = useState<JobSummary[]>([]);
  const [error, setError] = useState<unknown>(null);
  // Stable, because JobPage restarts its polling whenever this changes.
  const refreshJobs = useCallback(() => void api.jobs().then(setJobs).catch(() => undefined), []);

  useEffect(() => {
    Promise.all([api.session(), api.commands()])
      .then(([s, c]) => {
        setSession(s);
        setCommands(c);
      })
      .catch(setError);
  }, []);

  useEffect(() => {
    if (!session) return;
    let stopped = false;
    let timer = 0;
    const tick = async () => {
      try {
        const next = await api.jobs();
        if (!stopped) setJobs(next);
      } catch {
        // A missed refresh is not worth a banner; the next one will tell.
      }
      if (!stopped) timer = window.setTimeout(tick, JOBS_POLL_MS);
    };
    void tick();
    return () => {
      stopped = true;
      window.clearTimeout(timer);
    };
  }, [session]);

  if (error instanceof ApiError && error.status === 401) return <SignedOut />;
  if (error) {
    return (
      <div className="centered">
        <h2>sdm web is not reachable</h2>
        <ErrorBox error={error} />
        <p className="muted">Is `sdm web` still running?</p>
      </div>
    );
  }
  if (!session) return <div className="centered muted">Connecting…</div>;

  const [section, arg] = route.segments;
  const running = jobs.filter((j) => j.status === "running");

  let page;
  if (section === "run" && arg) {
    const command = commands.find((c) => c.name === arg);
    page = command ? (
      <CommandPage key={command.name} command={command} session={session} jobs={jobs} onStarted={refreshJobs} />
    ) : (
      <ErrorBox error={`No command "${arg}"`} />
    );
  } else if (section === "jobs" && arg) {
    page = <JobPage key={arg} id={arg} onChange={refreshJobs} />;
  } else if (section === "jobs") {
    page = <JobsPage jobs={jobs} />;
  } else if (section === "reports") {
    page = <ReportsPage />;
  } else if (section === "report") {
    const path = route.query.get("path") ?? "";
    page = <ReportPage key={path + route.query.get("view")} path={path} forceTable={route.query.get("view") === "table"} />;
  } else {
    page = <Home commands={commands} jobs={jobs} session={session} />;
  }

  return (
    <div className="layout">
      <nav className="sidebar">
        <a className="brand" href={href("/")}>
          sdm <span className="muted">{session.version}</span>
        </a>
        <div className="nav-label">Commands</div>
        {commands.map((c) => {
          const busy = running.some((j) => j.command === c.name);
          return (
            <a
              key={c.name}
              href={href(`/run/${c.name}`)}
              className={section === "run" && arg === c.name ? "active" : ""}
              title={c.help}
            >
              {c.name}
              {busy && <span className="dot" title="running" />}
            </a>
          );
        })}
        <div className="nav-label">Results</div>
        <a href={href("/jobs")} className={section === "jobs" ? "active" : ""}>
          Jobs {running.length > 0 && <span className="count">{running.length}</span>}
        </a>
        <a href={href("/reports")} className={section === "reports" || section === "report" ? "active" : ""}>
          Reports
        </a>
        <div className="sidebar-foot muted" title={session.out_root}>
          Local only · 127.0.0.1
        </div>
      </nav>
      <main className="content">{page}</main>
    </div>
  );
}

function SignedOut() {
  return (
    <div className="centered">
      <h2>Not signed in</h2>
      <p>
        Open the link <code>sdm web</code> printed in its terminal. It carries a token that changes on every launch, so
        a bookmark of an earlier one stops working.
      </p>
    </div>
  );
}
