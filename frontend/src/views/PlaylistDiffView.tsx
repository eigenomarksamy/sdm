import { useEffect, useMemo, useState } from "react";
import { api, ApiError, type TablePage } from "../api";
import { CopyButton, Empty, ErrorBox } from "../components";
import { baseName, plural } from "../format";
import { PlayButton } from "../player";
import { TableView } from "./TableView";

type Row = Record<string, string>;
type Tab = "missing" | "maybe" | "owned";

/**
 * `playlist-diff`'s two reports as one answer: what to go and get (missing),
 * what to check by ear (maybe — a different version, or a file with no artist
 * to confirm), and what the folder has (owned), each owned track with the file
 * it matched so a wrong match can be caught rather than trusted.
 *
 * Column names are `playlist_diff/command.py`'s.
 */
export function PlaylistDiffView({
  missing,
  matched,
  name,
  fallback,
}: {
  missing: string;
  matched: string;
  name: string;
  /** The file to show as a plain table if these turn out not to be playlist-diff's. */
  fallback: string;
}) {
  const [absent, setAbsent] = useState<Row[] | null>(null);
  const [owned, setOwned] = useState<Row[] | null>(null);
  const [foreign, setForeign] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [tab, setTab] = useState<Tab>("missing");
  const [filter, setFilter] = useState("");

  useEffect(() => {
    // Either file may be gone; a lone report still answers half the question.
    Promise.all([loadRows(missing), loadRows(matched)])
      .then(([a, o]) => {
        if (a === null && o === null) throw new Error(`Neither missing_${name}.csv nor matched_${name}.csv could be read.`);
        if ((a && !a.header.includes("status")) || (o && !o.header.includes("local_file"))) {
          setForeign(true);
          return;
        }
        setAbsent(a?.rows ?? []);
        setOwned(o?.rows ?? []);
      })
      .catch(setError);
  }, [missing, matched, name]);

  const rows = useMemo(() => {
    if (!absent || !owned) return [];
    const source = tab === "owned" ? owned : absent.filter((r) => r.status === tab);
    const needle = filter.trim().toLowerCase();
    return needle ? source.filter((r) => Object.values(r).join(" ").toLowerCase().includes(needle)) : source;
  }, [absent, owned, tab, filter]);

  if (error) return <ErrorBox error={error} />;
  if (foreign) return <TableView path={fallback} />;
  if (!absent || !owned) return <div className="muted">Loading…</div>;

  const missingCount = absent.filter((r) => r.status === "missing").length;
  const maybeCount = absent.filter((r) => r.status === "maybe").length;
  const total = absent.length + owned.length;
  const shopping = rows.map((r) => (r.artist ? `${r.artist} - ${r.title}` : r.title)).join("\n");

  return (
    <div>
      <div className="stats">
        <div className="stat">
          <strong>{total ? Math.round((100 * owned.length) / total) : 0}%</strong>
          <span>of “{name}” in the folder</span>
        </div>
        <div className="stat">
          <strong>{missingCount.toLocaleString()}</strong>
          <span>missing</span>
        </div>
        <div className="stat">
          <strong>{maybeCount.toLocaleString()}</strong>
          <span>maybe</span>
        </div>
        <div className="stat">
          <strong>{owned.length.toLocaleString()}</strong>
          <span>owned</span>
        </div>
      </div>

      <div className="toolbar">
        <div className="segmented">
          {(
            [
              ["missing", `Missing (${missingCount})`],
              ["maybe", `Maybe (${maybeCount})`],
              ["owned", `Owned (${owned.length})`],
            ] as const
          ).map(([key, label]) => (
            <button key={key} className={tab === key ? "active" : ""} onClick={() => setTab(key)}>
              {label}
            </button>
          ))}
        </div>
        <input type="search" placeholder="Filter…" value={filter} onChange={(e) => setFilter(e.target.value)} />
        <span className="spacer" />
        {rows.length > 0 && <CopyButton text={shopping} label={`Copy ${plural(rows.length, "track")} as a list`} />}
      </div>

      {tab === "maybe" && rows.length > 0 && (
        <p className="muted">
          Not counted as owned: the folder has something close — a different version, or a file with no artist tag to
          confirm. Play the local file to decide.
        </p>
      )}

      {rows.length === 0 ? (
        <Empty>{filter ? "Nothing matches the filter." : tab === "missing" ? "Nothing missing." : "None."}</Empty>
      ) : tab === "owned" ? (
        <div className="table-scroll">
          <table className="table">
            <thead>
              <tr>
                <th className="num">#</th>
                <th>Artist</th>
                <th>Title</th>
                <th>Matched file</th>
                <th>Via</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r["#"]}>
                  <td className="num muted">{r["#"]}</td>
                  <td>{r.artist}</td>
                  <td>{r.title}</td>
                  <td>
                    <LocalFile path={r.local_file} title={r.title} artist={r.artist} />
                  </td>
                  <td className="muted">{r.matched_via}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="table-scroll">
          <table className="table">
            <thead>
              <tr>
                <th className="num">#</th>
                <th>Artist</th>
                <th>Title</th>
                <th>Album</th>
                <th className="num">Length</th>
                {tab === "maybe" && <th>Closest file in the folder</th>}
                <th>Spotify</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r["#"]}>
                  <td className="num muted">{r["#"]}</td>
                  <td>{r.artist}</td>
                  <td>{r.title}</td>
                  <td className="muted">{r.album}</td>
                  <td className="num">{r.duration}</td>
                  {tab === "maybe" && (
                    <td>
                      {r.closest_local_file && (
                        <LocalFile path={r.closest_local_file} title={r.title} artist={r.artist} />
                      )}
                      {r.note && <div className="muted small">{r.note}</div>}
                    </td>
                  )}
                  <td className="nowrap">
                    {r.spotify_url ? (
                      <a href={r.spotify_url} target="_blank" rel="noreferrer" title={r.isrc ? `ISRC ${r.isrc}` : undefined}>
                        Open ↗
                      </a>
                    ) : (
                      <span className="muted">{r.isrc}</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function LocalFile({ path, title, artist }: { path: string; title: string; artist: string }) {
  return (
    <span className="with-play">
      <PlayButton item={{ path, title: title || baseName(path), subtitle: artist }} />
      <span className="mono" title={path}>
        {baseName(path)}
      </span>
    </span>
  );
}

async function loadRows(path: string): Promise<{ header: string[]; rows: Row[] } | null> {
  let page: TablePage;
  try {
    page = await api.table(path, { limit: 50000 });
  } catch (e) {
    if (e instanceof ApiError && (e.status === 404 || e.status === 403)) return null;
    throw e;
  }
  return {
    header: page.header,
    rows: page.rows.map((cells) => Object.fromEntries(page.header.map((h, i) => [h, cells[i] ?? ""]))),
  };
}
