import { useEffect, useState } from "react";
import { api, rawUrl, type ReportFile } from "../api";
import { Empty } from "../components";
import { ago, baseName, bytes, dirName } from "../format";
import { href } from "../router";
import { DuplicatesView } from "../views/DuplicatesView";
import { PlaylistDiffView } from "../views/PlaylistDiffView";
import { QualityView } from "../views/QualityView";
import { TableView } from "../views/TableView";

/**
 * Which view a report gets, from its name and folder. The names are each
 * feature's own: `duplicates.json` is `write_duplicate_report`'s in any folder
 * (`sdm duplicates` and `sdm rekordbox` both write it), while playlist-diff's
 * missing_/matched_ pair also needs its folder, because catalog's
 * `missing_metadata_<folder>.csv` has the same shape of name. `quality_<folder>.csv`
 * is quality's default name; its view checks the columns, so a stray file of
 * that name still opens as a table. A file that matches nothing opens as one too.
 */
export type View =
  | { kind: "duplicates"; json: string }
  | { kind: "playlist"; missing: string; matched: string; name: string }
  | { kind: "quality" }
  | { kind: "table" }
  | { kind: "raw" };

export function viewFor(path: string): View {
  const name = baseName(path);
  const folder = dirName(path);
  const sibling = (n: string) => (folder ? `${folder}${path.includes("\\") ? "\\" : "/"}${n}` : n);
  if (name === "duplicates.json" || name === "duplicates.csv") {
    return { kind: "duplicates", json: sibling("duplicates.json") };
  }
  const pl = /^(missing|matched)_(.+)\.csv$/.exec(name);
  if (pl && baseName(folder) === "playlist-diff") {
    return { kind: "playlist", missing: sibling(`missing_${pl[2]}.csv`), matched: sibling(`matched_${pl[2]}.csv`), name: pl[2] };
  }
  if (/^quality_.+\.csv$/i.test(name)) return { kind: "quality" };
  if (name.toLowerCase().endsWith(".csv")) return { kind: "table" };
  return { kind: "raw" };
}

export function viewLabel(path: string): string {
  return {
    duplicates: "duplicate groups",
    playlist: "playlist diff",
    quality: "audio quality",
    table: "table",
    raw: "file",
  }[viewFor(path).kind];
}

const TAB_LABEL = { duplicates: "Groups", playlist: "Playlist diff", quality: "Quality" } as const;

export function ReportPage({ path, forceTable }: { path: string; forceTable: boolean }) {
  const [info, setInfo] = useState<ReportFile | null>(null);
  useEffect(() => {
    api
      .reports()
      .then((r) => setInfo(r.files.find((f) => f.rel === path) ?? null))
      .catch(() => setInfo(null));
  }, [path]);

  if (!path) return <Empty>No report chosen.</Empty>;
  const view = viewFor(path);
  const isCsv = path.toLowerCase().endsWith(".csv");
  const dedicated = view.kind === "duplicates" || view.kind === "playlist" || view.kind === "quality";
  const showTable = isCsv && (forceTable || !dedicated);

  return (
    <div className="page">
      <header className="page-head">
        <div className="crumbs">
          <a href={href("/reports")}>Reports</a> / <span className="mono">{path}</span>
        </div>
        <div className="toolbar">
          {info && (
            <span className="muted">
              {bytes(info.size)} · written {ago(info.mtime)}
            </span>
          )}
          <span className="spacer" />
          {isCsv && dedicated && (
            <div className="segmented">
              <a className={!showTable ? "active" : ""} href={href("/report", { path })}>
                {TAB_LABEL[view.kind]}
              </a>
              <a className={showTable ? "active" : ""} href={href("/report", { path, view: "table" })}>
                Table
              </a>
            </div>
          )}
          <a className="button ghost" href={rawUrl(path)} target="_blank" rel="noreferrer">
            Open raw
          </a>
        </div>
      </header>

      {showTable ? (
        <TableView path={path} />
      ) : view.kind === "duplicates" ? (
        <DuplicatesView path={view.json} />
      ) : view.kind === "playlist" ? (
        <PlaylistDiffView missing={view.missing} matched={view.matched} name={view.name} fallback={path} />
      ) : view.kind === "quality" ? (
        <QualityView path={path} />
      ) : (
        <Empty>
          No view for this file type. <a href={rawUrl(path)} target="_blank" rel="noreferrer">Open it raw</a>.
        </Empty>
      )}
    </div>
  );
}
