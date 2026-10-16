import { useEffect, useState } from "react";
import { api, type ReportFile } from "../api";
import { Empty, ErrorBox } from "../components";
import { ago, bytes } from "../format";
import { href } from "../router";
import { viewLabel } from "./ReportPage";

export function ReportsPage() {
  const [data, setData] = useState<{ root: string; files: ReportFile[] } | null>(null);
  const [error, setError] = useState<unknown>(null);
  useEffect(() => {
    api.reports().then(setData).catch(setError);
  }, []);

  if (error) return <ErrorBox error={error} />;
  if (!data) return <div className="muted">Loading…</div>;

  // Grouped by the top folder, which is the feature that wrote it.
  const groups = new Map<string, ReportFile[]>();
  for (const f of data.files) {
    const top = f.rel.includes("/") ? f.rel.split("/")[0] : "(root)";
    groups.set(top, [...(groups.get(top) ?? []), f]);
  }
  const names = [...groups.keys()].sort();

  return (
    <div className="page">
      <header className="page-head">
        <h1>Reports</h1>
        <p className="muted">
          Everything under <code>{data.root}</code>, newest first in each folder.
        </p>
      </header>
      {names.length === 0 && <Empty>No reports yet. Run a command and they appear here.</Empty>}
      {names.map((name) => (
        <section key={name}>
          <h2>
            <code>{name}/</code>
          </h2>
          <table className="table">
            <thead>
              <tr>
                <th>File</th>
                <th>Opens as</th>
                <th className="num">Size</th>
                <th>Written</th>
              </tr>
            </thead>
            <tbody>
              {groups.get(name)!.map((f) => (
                <tr key={f.rel}>
                  <td>
                    <a href={href("/report", { path: f.rel })}>{f.rel.slice(name.length + 1) || f.name}</a>
                  </td>
                  <td className="muted">{viewLabel(f.rel)}</td>
                  <td className="num muted">{bytes(f.size)}</td>
                  <td className="muted" title={new Date(f.mtime * 1000).toLocaleString()}>
                    {ago(f.mtime)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ))}
    </div>
  );
}
