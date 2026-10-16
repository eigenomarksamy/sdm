import { useEffect, useState, type SubmitEvent } from "react";
import { api, ApiError, type Command, type FormValues, type JobSummary, type ReportFile, type Session } from "../api";
import { ErrorBox, FieldInput, StatusBadge } from "../components";
import { ago, store } from "../format";
import { href, navigate } from "../router";

/**
 * A form for one command, built entirely from its argparse definition. Empty
 * fields are left out of the run, so argparse applies its own defaults rather
 * than this page restating them — the placeholders show what they are.
 */
export function CommandPage({
  command,
  session,
  jobs,
  onStarted,
}: {
  command: Command;
  session: Session;
  jobs: JobSummary[];
  onStarted: () => void;
}) {
  const storeKey = `sdm.form.${command.name}`;
  const [values, setValues] = useState<FormValues>(() => store.get(storeKey, {}));
  const [error, setError] = useState<unknown>(null);
  const [busyJob, setBusyJob] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [reports, setReports] = useState<ReportFile[]>([]);

  useEffect(() => store.set(storeKey, values), [storeKey, values]);
  useEffect(() => {
    api
      .reports()
      .then((r) => setReports(r.files.filter((f) => f.rel.split("/")[0] === command.name)))
      .catch(() => setReports([]));
  }, [command.name]);

  const fields = [...command.fields].sort((a, b) => Number(b.positional) - Number(a.positional));
  const recent = jobs.filter((j) => j.command === command.name).slice(0, 5);

  const submit = async (e: SubmitEvent<HTMLFormElement>) => {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    setBusyJob(null);
    try {
      const job = await api.startJob(command.name, values);
      onStarted();
      navigate(`/jobs/${job.id}`);
    } catch (err) {
      setError(err);
      if (err instanceof ApiError && err.status === 409 && typeof err.body?.job === "string") setBusyJob(err.body.job);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="page">
      <header className="page-head">
        <h1>
          <code>sdm {command.name}</code>
        </h1>
        <p>{command.help}</p>
        {command.description && command.description !== command.help && (
          <p className="muted">{command.description}</p>
        )}
      </header>

      <form className="form" onSubmit={submit}>
        {fields.map((field) => (
          <div key={field.dest}>
            <FieldInput
              field={field}
              value={values[field.dest] ?? null}
              onChange={(v) => setValues((prev) => ({ ...prev, [field.dest]: v }))}
            />
            {field.dest === "client_id" && !session.spotify_client_id && (
              <p className="help warn">
                <code>SDM_SPOTIFY_CLIENT_ID</code> is not set where <code>sdm web</code> was started. A playlist link
                needs one here or in the environment; a CSV export needs none.
              </p>
            )}
          </div>
        ))}
        <div className="form-actions">
          <button className="primary" type="submit" disabled={submitting}>
            {submitting ? "Starting…" : `Run sdm ${command.name}`}
          </button>
          <button type="button" className="ghost" onClick={() => setValues({})}>
            Reset
          </button>
        </div>
        <ErrorBox error={error} />
        {busyJob && (
          <p>
            <a href={href(`/jobs/${busyJob}`)}>Go to the running job →</a>
          </p>
        )}
      </form>

      <div className="two-col">
        <section>
          <h2>Recent runs</h2>
          {recent.length === 0 ? (
            <p className="muted">None in this session.</p>
          ) : (
            <ul className="plain-list">
              {recent.map((j) => (
                <li key={j.id}>
                  <a href={href(`/jobs/${j.id}`)}>
                    <StatusBadge status={j.status} cancelling={j.cancel_requested} /> job {j.id}
                  </a>{" "}
                  <span className="muted">{ago(j.started)}</span>
                </li>
              ))}
            </ul>
          )}
        </section>
        <section>
          <h2>
            Reports in <code>out/{command.name}/</code>
          </h2>
          {reports.length === 0 ? (
            <p className="muted">None yet.</p>
          ) : (
            <ul className="plain-list">
              {reports.map((r) => (
                <li key={r.rel}>
                  <a href={href("/report", { path: r.rel })}>{r.name}</a>{" "}
                  <span className="muted">{ago(r.mtime)}</span>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </div>
  );
}
