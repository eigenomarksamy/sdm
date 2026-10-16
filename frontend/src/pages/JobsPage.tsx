import type { JobSummary } from "../api";
import { Empty, StatusBadge } from "../components";
import { ago, elapsed } from "../format";
import { href } from "../router";

export function JobsPage({ jobs }: { jobs: JobSummary[] }) {
  return (
    <div className="page">
      <header className="page-head">
        <h1>Jobs</h1>
        <p className="muted">
          Runs started from this page since <code>sdm web</code> started. They are not kept across restarts; what they
          wrote is, under Reports.
        </p>
      </header>
      {jobs.length === 0 ? (
        <Empty>No jobs yet. Pick a command on the left.</Empty>
      ) : (
        <table className="table">
          <thead>
            <tr>
              <th>#</th>
              <th>Status</th>
              <th>Command</th>
              <th>Started</th>
              <th>Took</th>
            </tr>
          </thead>
          <tbody>
            {jobs.map((j) => (
              <tr key={j.id}>
                <td>
                  <a href={href(`/jobs/${j.id}`)}>{j.id}</a>
                </td>
                <td>
                  <StatusBadge status={j.status} cancelling={j.cancel_requested} />
                </td>
                <td className="mono">
                  <a href={href(`/jobs/${j.id}`)}>{j.display}</a>
                </td>
                <td className="muted">{ago(j.started)}</td>
                <td className="muted">{elapsed(j.started, j.ended)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
