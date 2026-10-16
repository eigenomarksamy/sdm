import { useEffect, useState } from "react";
import { api, type TablePage } from "../api";
import { ErrorBox } from "../components";
import { baseName, isAudioPath, plural } from "../format";
import { PlayButton } from "../player";

const PAGE = 100;

/**
 * Any CSV, paged, filtered and sorted on the server. The fallback for every
 * report without a dedicated view, and the "Table" tab of those with one.
 * A cell holding an audio path gets a play button; a URL is a link.
 */
export function TableView({ path }: { path: string }) {
  const [page, setPage] = useState<TablePage | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [offset, setOffset] = useState(0);
  const [typed, setTyped] = useState("");
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<number | null>(null);
  const [desc, setDesc] = useState(false);

  useEffect(() => {
    const t = window.setTimeout(() => {
      setQuery(typed);
      setOffset(0);
    }, 250);
    return () => window.clearTimeout(t);
  }, [typed]);

  useEffect(() => {
    let current = true;
    api
      .table(path, { offset, limit: PAGE, q: query, sort, desc })
      .then((p) => current && (setPage(p), setError(null)))
      .catch((e) => current && setError(e));
    return () => {
      current = false;
    };
  }, [path, offset, query, sort, desc]);

  if (error) return <ErrorBox error={error} />;
  if (!page) return <div className="muted">Loading…</div>;

  const streamed = page.mode === "stream";
  const count = page.matched ?? page.total;
  const end = Math.min(offset + page.rows.length, count);

  return (
    <div className="table-view">
      <div className="toolbar">
        <input
          type="search"
          placeholder={streamed ? "Too large to filter" : "Filter rows…"}
          disabled={streamed}
          value={typed}
          onChange={(e) => setTyped(e.target.value)}
        />
        <span className="muted">
          {count ? `${(offset + 1).toLocaleString()}–${end.toLocaleString()} of ${plural(count, "row")}` : "no rows"}
          {page.matched !== null && page.matched !== page.total && ` (filtered from ${page.total.toLocaleString()})`}
          {streamed && " · large file: paged only, no sort or filter"}
        </span>
        <span className="spacer" />
        <button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>
          ← Prev
        </button>
        <button disabled={end >= count} onClick={() => setOffset(offset + PAGE)}>
          Next →
        </button>
      </div>
      <div className="table-scroll">
        <table className="table">
          <thead>
            <tr>
              {page.header.map((h, i) => (
                <th
                  key={i}
                  className={streamed ? "" : "sortable"}
                  onClick={() => {
                    if (streamed) return;
                    if (sort === i) setDesc(!desc);
                    else {
                      setSort(i);
                      setDesc(false);
                    }
                    setOffset(0);
                  }}
                >
                  {h}
                  {sort === i ? (desc ? " ↓" : " ↑") : ""}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {page.rows.map((row, r) => (
              <tr key={offset + r}>
                {page.header.map((_, c) => (
                  <td key={c}>
                    <Cell value={row[c] ?? ""} />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Cell({ value }: { value: string }) {
  if (/^https?:\/\//.test(value)) {
    return (
      <a href={value} target="_blank" rel="noreferrer">
        {value}
      </a>
    );
  }
  if (isAudioPath(value)) {
    return (
      <span className="with-play">
        <PlayButton item={{ path: value, title: baseName(value) }} />
        <span className="mono" title={value}>
          {value}
        </span>
      </span>
    );
  }
  return <>{value}</>;
}
