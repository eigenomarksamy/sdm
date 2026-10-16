import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { CopyButton, Empty, ErrorBox } from "../components";
import { baseName, clock, dirName, extension, plural } from "../format";
import { PlayButton } from "../player";

// The shape `core.report.write_duplicate_report` writes to duplicates.json —
// the same for `sdm duplicates` and `sdm rekordbox`, which is why one view
// serves both.
interface DupTrack {
  id: string;
  title: string;
  artist: string;
  file_path: string;
  bpm: number | null;
  key: string | null;
  duration_seconds: number | null;
}

interface DupGroup {
  group_id: number;
  matched_rules: string[];
  tracks: DupTrack[];
}

type SortKey = "id" | "size" | "spread";

const GROUPS_PER_PAGE = 50;
const TRACKS_SHOWN = 30;

/**
 * Duplicate groups side by side, with what differs between the copies
 * highlighted, and a play button on every file. Read-only, like the commands
 * that wrote the report: deciding which copy to keep is left to the user, in
 * their own file manager.
 */
export function DuplicatesView({ path }: { path: string }) {
  const [groups, setGroups] = useState<DupGroup[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [filter, setFilter] = useState("");
  const [sort, setSort] = useState<SortKey>("id");
  const [shown, setShown] = useState(GROUPS_PER_PAGE);

  useEffect(() => {
    api.raw<DupGroup[]>(path).then(setGroups).catch(setError);
  }, [path]);

  const visible = useMemo(() => {
    if (!groups) return [];
    const needle = filter.trim().toLowerCase();
    const matched = needle
      ? groups.filter((g) =>
          g.tracks.some((t) => `${t.title} ${t.artist} ${t.file_path}`.toLowerCase().includes(needle)),
        )
      : groups;
    const by: Record<SortKey, (a: DupGroup, b: DupGroup) => number> = {
      id: (a, b) => a.group_id - b.group_id,
      size: (a, b) => b.tracks.length - a.tracks.length || a.group_id - b.group_id,
      spread: (a, b) => spread(b) - spread(a) || a.group_id - b.group_id,
    };
    return [...matched].sort(by[sort]);
  }, [groups, filter, sort]);

  if (error) return <ErrorBox error={error} />;
  if (!groups) return <div className="muted">Loading…</div>;
  if (groups.length === 0) return <Empty>No duplicate groups in this report. A clean library, or a run that compared nothing — check its log.</Empty>;

  const tracks = groups.reduce((n, g) => n + g.tracks.length, 0);
  const sizes = new Map<number, number>();
  for (const g of groups) sizes.set(g.tracks.length, (sizes.get(g.tracks.length) ?? 0) + 1);
  // Rules are "metadata" and "fingerprint" (core/duplicates.py), or "title+artist"
  // for `rekordbox --duplicates-by-name`, which never claims to be audio-confirmed.
  const unconfirmed = groups.filter(
    (g) => g.matched_rules.includes("metadata") && !g.matched_rules.includes("fingerprint"),
  ).length;

  return (
    <div>
      <div className="stats">
        <Stat value={groups.length} label="groups" />
        <Stat value={tracks} label="tracks in them" />
        {[...sizes.entries()]
          .sort((a, b) => a[0] - b[0])
          .slice(0, 4)
          .map(([size, n]) => (
            <Stat key={size} value={n} label={size === 2 ? "pairs" : size === 3 ? "triples" : `of ${size}`} />
          ))}
      </div>

      {unconfirmed > 0 && (
        <div className="warn-box">
          {unconfirmed === groups.length ? "None of these groups were" : `${plural(unconfirmed, "group")} here were not`}{" "}
          confirmed by audio fingerprint. Groups from <code>--skip-fingerprint</code> are metadata candidates, chained
          together by similar durations — use them to size a run, not as duplicates.
        </div>
      )}

      <div className="toolbar">
        <input
          type="search"
          placeholder="Filter by title, artist or path…"
          value={filter}
          onChange={(e) => {
            setFilter(e.target.value);
            setShown(GROUPS_PER_PAGE);
          }}
        />
        <label className="inline">
          Sort
          <select value={sort} onChange={(e) => setSort(e.target.value as SortKey)}>
            <option value="id">by group number</option>
            <option value="size">largest groups first</option>
            <option value="spread">widest duration spread first</option>
          </select>
        </label>
        <span className="muted">{filter && plural(visible.length, "group")}</span>
      </div>

      {visible.slice(0, shown).map((g) => (
        <GroupCard key={g.group_id} group={g} playGroup={`${path}#${g.group_id}`} />
      ))}
      {visible.length > shown && (
        <button className="more" onClick={() => setShown(shown + GROUPS_PER_PAGE)}>
          Show more ({plural(visible.length - shown, "group")} left)
        </button>
      )}
    </div>
  );
}

function GroupCard({ group, playGroup }: { group: DupGroup; playGroup: string }) {
  const [all, setAll] = useState(false);
  const rows = all ? group.tracks : group.tracks.slice(0, TRACKS_SHOWN);

  // Which columns differ between the copies: often the whole story (a FLAC and
  // an MP3 of one release, or one file mis-tagged).
  const differs = (get: (t: DupTrack) => unknown) =>
    new Set(group.tracks.map((t) => String(get(t) ?? "").toLowerCase())).size > 1;
  const diff = {
    title: differs((t) => t.title),
    artist: differs((t) => t.artist),
    bpm: differs((t) => t.bpm),
    key: differs((t) => t.key),
    format: differs((t) => extension(t.file_path)),
    folder: differs((t) => dirName(t.file_path)),
  };
  const s = spread(group);

  return (
    <article className="group-card">
      <header>
        <strong>#{group.group_id}</strong>
        {group.matched_rules.map((r) => (
          <span key={r} className={`badge rule-${r}`}>
            {r}
          </span>
        ))}
        <span className="muted">
          {plural(group.tracks.length, "track")}
          {s > 0 && ` · durations within ${s.toFixed(2)}s`}
        </span>
      </header>
      <table className="table dup-table">
        <thead>
          <tr>
            <th aria-label="Play" />
            <th>Title</th>
            <th>Artist</th>
            <th className="num">BPM</th>
            <th>Key</th>
            <th className="num">Length</th>
            <th>Format</th>
            <th>File</th>
            <th aria-label="Copy path" />
          </tr>
        </thead>
        <tbody>
          {rows.map((t) => (
            <tr key={t.id + t.file_path}>
              <td>
                <PlayButton
                  item={{ path: t.file_path, title: t.title || baseName(t.file_path), subtitle: t.artist, group: playGroup }}
                />
              </td>
              <td className={diff.title ? "diff" : ""}>{t.title}</td>
              <td className={diff.artist ? "diff" : ""}>{t.artist}</td>
              <td className={`num ${diff.bpm ? "diff" : ""}`}>{t.bpm ?? ""}</td>
              <td className={diff.key ? "diff" : ""}>{t.key ?? ""}</td>
              <td className="num">{clock(t.duration_seconds, true)}</td>
              <td className={diff.format ? "diff" : ""}>{extension(t.file_path).toUpperCase()}</td>
              <td className="file-cell" title={t.file_path}>
                <span className="file-name">{baseName(t.file_path)}</span>
                <span className={`file-folder ${diff.folder ? "diff" : ""}`}>{dirName(t.file_path)}</span>
              </td>
              <td>
                <CopyButton text={t.file_path} label="Copy path" />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {group.tracks.length > TRACKS_SHOWN && (
        <button className="more" onClick={() => setAll(!all)}>
          {all ? "Show fewer" : `Show all ${group.tracks.length.toLocaleString()} tracks`}
        </button>
      )}
    </article>
  );
}

function Stat({ value, label }: { value: number; label: string }) {
  return (
    <div className="stat">
      <strong>{value.toLocaleString()}</strong>
      <span>{label}</span>
    </div>
  );
}

function spread(g: DupGroup): number {
  const d = g.tracks.map((t) => t.duration_seconds).filter((x): x is number => x !== null);
  return d.length > 1 ? Math.max(...d) - Math.min(...d) : 0;
}
