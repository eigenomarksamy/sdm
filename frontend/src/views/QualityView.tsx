import { Fragment, useEffect, useMemo, useState } from "react";
import { api, ApiError } from "../api";
import { CopyButton, Empty, ErrorBox } from "../components";
import { baseName, clock, dirName, isAudioPath, plural } from "../format";
import { PlayButton } from "../player";
import { TableView } from "./TableView";

type Row = Record<string, string>;
type SortKey = "path" | "issues" | "cutoff" | "loud" | "quiet" | "clip" | "peak";

const ROWS_PER_PAGE = 100;

/** Columns that say this CSV is `quality`'s report, not just a file of that name. */
const REQUIRED = ["file_path", "bitrate_kbps", "meta_bitrate_kbps", "cutoff_khz", "issues", "flags"];

// Kinds from `quality/compare.py`. Problems in the audio itself are red; a claim
// the measurement contradicts is amber, because the audio may be fine and only
// the label wrong.
const AUDIO_PROBLEMS = new Set([
  "undecodable",
  "decode errors",
  "transcode?",
  "lossy source?",
  "upsampled?",
  "padded bits",
  "clipping",
  "out of phase",
]);

// The tolerances `compare.py` flags by, for highlighting a claim beside its
// measurement. The flags themselves come from the report; this only paints.
const BITRATE_TOLERANCE = 0.15;
const DURATION_TOLERANCE = { meta: 1, rb: 2 };

/**
 * `quality`'s report as what it is: for each file, what the audio measures
 * next to what its metadata claims — its own header and tags, and Rekordbox's
 * database — with every claim the measurement contradicts highlighted, and the
 * issues it raised to filter by. A row opens into the full side-by-side.
 *
 * Column names are `quality/command.py`'s.
 */
export function QualityView({ path }: { path: string }) {
  const [rows, setRows] = useState<Row[] | null>(null);
  const [foreign, setForeign] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [filter, setFilter] = useState("");
  const [kind, setKind] = useState<string | null>(null);
  const [flaggedOnly, setFlaggedOnly] = useState(false);
  const [sort, setSort] = useState<SortKey>("path");
  const [shown, setShown] = useState(ROWS_PER_PAGE);
  const [open, setOpen] = useState<string | null>(null);

  useEffect(() => {
    setRows(null);
    api
      .table(path, { limit: 100000 })
      .then((page) => {
        if (!REQUIRED.every((c) => page.header.includes(c))) {
          setForeign(true);
          return;
        }
        setRows(page.rows.map((cells) => Object.fromEntries(page.header.map((h, i) => [h, cells[i] ?? ""]))));
      })
      .catch((e) => (e instanceof ApiError && e.status === 404 ? setError(new Error("This report no longer exists.")) : setError(e)));
  }, [path]);

  const kinds = useMemo(() => {
    const counts = new Map<string, number>();
    for (const r of rows ?? []) for (const k of issues(r)) counts.set(k, (counts.get(k) ?? 0) + 1);
    return [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  }, [rows]);

  const visible = useMemo(() => {
    if (!rows) return [];
    const needle = filter.trim().toLowerCase();
    const matched = rows.filter(
      (r) =>
        (!kind || issues(r).includes(kind)) &&
        (!flaggedOnly || r.issues) &&
        (!needle || `${r.title} ${r.artist} ${r.file_path} ${r.flags}`.toLowerCase().includes(needle)),
    );
    const by: Record<SortKey, (a: Row, b: Row) => number> = {
      path: () => 0, // the report is already in path order
      issues: (a, b) => issues(b).length - issues(a).length,
      cutoff: (a, b) => ascending(a.cutoff_khz, b.cutoff_khz),
      loud: (a, b) => descending(a.integrated_lufs, b.integrated_lufs),
      quiet: (a, b) => ascending(a.integrated_lufs, b.integrated_lufs),
      clip: (a, b) => descending(a.clip_rate_pct, b.clip_rate_pct),
      peak: (a, b) => descending(a.true_peak_dbtp, b.true_peak_dbtp),
    };
    return sort === "path" ? matched : [...matched].sort(by[sort]);
  }, [rows, filter, kind, flaggedOnly, sort]);

  if (error) return <ErrorBox error={error} />;
  if (foreign) return <TableView path={path} />;
  if (!rows) return <div className="muted">Loading…</div>;
  if (rows.length === 0) return <Empty>No audio files in this report.</Empty>;

  const undecodable = rows.filter((r) => issues(r).includes("undecodable")).length;
  const flagged = rows.filter((r) => r.issues).length;
  const lufs = numbers(rows, "integrated_lufs").sort((a, b) => a - b);
  const overs = numbers(rows, "true_peak_dbtp").filter((v) => v > 0).length;
  const withRb = rows.filter((r) => r.rb_match).length;
  const resetPaging = () => setShown(ROWS_PER_PAGE);

  return (
    <div>
      <div className="stats">
        <Stat value={rows.length.toLocaleString()} label="files" />
        <Stat value={flagged.toLocaleString()} label="with an issue" />
        {lufs.length > 0 && <Stat value={`${lufs[Math.floor(lufs.length / 2)].toFixed(1)}`} label="median LUFS" />}
        <Stat value={overs.toLocaleString()} label="true peak above 0 dBTP" />
        <Stat
          value={withRb ? withRb.toLocaleString() : "—"}
          label={withRb ? "matched in Rekordbox" : "no Rekordbox data"}
        />
      </div>

      {undecodable > 0 && (
        <div className="warn-box">
          {plural(undecodable, "file")} could not be decoded at all — see the{" "}
          <button className="link" onClick={() => (setKind("undecodable"), resetPaging())}>
            undecodable
          </button>{" "}
          issue.
        </div>
      )}

      {kinds.length > 0 && (
        <div className="chips" role="group" aria-label="Filter by issue">
          <button className={!kind ? "chip active" : "chip"} onClick={() => (setKind(null), resetPaging())}>
            All issues
          </button>
          {kinds.map(([k, n]) => (
            <button
              key={k}
              className={`chip ${kind === k ? "active" : ""} ${AUDIO_PROBLEMS.has(k) ? "bad" : "warn"}`}
              onClick={() => (setKind(kind === k ? null : k), resetPaging())}
            >
              {k} <span className="chip-count">{n.toLocaleString()}</span>
            </button>
          ))}
        </div>
      )}

      <p className="muted small">
        An issue with a “?” is evidence, not a verdict: a spectral cutoff is what a transcode leaves behind, and also
        what a few honest encoders and lo-fi masters produce. Play the file to decide.
      </p>

      <div className="toolbar">
        <input
          type="search"
          placeholder="Filter by title, artist, path or issue…"
          value={filter}
          onChange={(e) => (setFilter(e.target.value), resetPaging())}
        />
        <label className="inline">
          <input type="checkbox" checked={flaggedOnly} onChange={(e) => (setFlaggedOnly(e.target.checked), resetPaging())} />
          with an issue only
        </label>
        <label className="inline">
          Sort
          <select value={sort} onChange={(e) => setSort(e.target.value as SortKey)}>
            <option value="path">by path</option>
            <option value="issues">most issues first</option>
            <option value="cutoff">lowest spectral cutoff first</option>
            <option value="loud">loudest first</option>
            <option value="quiet">quietest first</option>
            <option value="clip">most clipping first</option>
            <option value="peak">highest true peak first</option>
          </select>
        </label>
        <span className="muted">{plural(visible.length, "file")}</span>
      </div>

      {visible.length === 0 ? (
        <Empty>Nothing matches.</Empty>
      ) : (
        <div className="table-scroll">
          <table className="table quality-table">
            <thead>
              <tr>
                <th aria-label="Play" />
                <th aria-label="Details" />
                <th>Track</th>
                <th>Issues</th>
                <th>Format</th>
                <th className="num">Bitrate</th>
                <th className="num">Cutoff</th>
                <th className="num">Rate · depth</th>
                <th className="num">Loudness</th>
                <th className="num">True peak</th>
                <th className="num">Clipped</th>
              </tr>
            </thead>
            <tbody>
              {visible.slice(0, shown).map((r) => (
                <Fragment key={r.file_path}>
                  <QualityRow row={r} open={open === r.file_path} onToggle={() => setOpen(open === r.file_path ? null : r.file_path)} />
                  {open === r.file_path && (
                    <tr className="detail-row">
                      <td colSpan={11}>
                        <Detail row={r} />
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {visible.length > shown && (
        <button className="more" onClick={() => setShown(shown + ROWS_PER_PAGE)}>
          Show more ({plural(visible.length - shown, "file")} left)
        </button>
      )}
    </div>
  );
}

function QualityRow({ row: r, open, onToggle }: { row: Row; open: boolean; onToggle: () => void }) {
  const lossless = isLossless(r.codec);
  const rate = sampleRate(r.sample_rate);
  // An untagged file is named by its file name, so the line under it names the
  // folder instead of repeating it.
  const titled = !!r.title && r.title !== "Unknown";
  return (
    <tr className={open ? "open" : ""}>
      <td>
        {isAudioPath(r.file_path) && (
          <PlayButton item={{ path: r.file_path, title: r.title || baseName(r.file_path), subtitle: r.artist }} />
        )}
      </td>
      <td>
        <button
          className="ghost small toggle"
          onClick={onToggle}
          aria-expanded={open}
          aria-label={open ? "Hide details" : "Show details"}
          title={open ? "Hide details" : "Measured vs. claimed, in full"}
        >
          {/* Not a triangle: beside the play button, ▸ reads as a second ▶. */}
          {open ? "−" : "+"}
        </button>
      </td>
      <td className="file-cell" title={r.file_path}>
        <span className="file-name">
          {titled ? r.title : baseName(r.file_path)}
          {r.artist && r.artist !== "Unknown" && <span className="muted"> — {r.artist}</span>}
        </span>
        <span className="file-sub">{titled ? baseName(r.file_path) : baseName(dirName(r.file_path))}</span>
      </td>
      <td>
        <Issues row={r} />
      </td>
      <td>
        {r.codec.toUpperCase()}
        {r.encoder && (
          <div className="claims encoder" title={r.encoder}>
            {r.encoder}
          </div>
        )}
      </td>
      <td className="num">
        {kbps(r.bitrate_kbps)}
        {!lossless && (
          <Claims
            items={[
              ["tags", kbps(r.meta_bitrate_kbps), bitrateDiffers(r.meta_bitrate_kbps, r.bitrate_kbps)],
              ["rb", kbps(r.rb_bitrate_kbps), bitrateDiffers(r.rb_bitrate_kbps, r.bitrate_kbps)],
            ]}
          />
        )}
      </td>
      <td className="num">
        {r.cutoff_khz ? `${Number(r.cutoff_khz).toFixed(1)} kHz` : r.bitrate_kbps ? <span className="muted">full band</span> : ""}
        {r.cutoff_khz && <div className="claims">{r.cutoff_sharp === "yes" ? "sharp" : "soft roll-off"}</div>}
      </td>
      <td className="num">
        {[rate, r.bit_depth && `${r.bit_depth}-bit`].filter(Boolean).join(" · ")}
        <Claims
          items={[
            ["tags", sampleRate(r.meta_sample_rate), differs(r.meta_sample_rate, r.sample_rate)],
            ["rb", sampleRate(r.rb_sample_rate), differs(r.rb_sample_rate, r.sample_rate)],
          ]}
          hideSame
        />
      </td>
      <td className="num">
        {r.integrated_lufs && `${r.integrated_lufs} LUFS`}
        {r.loudness_range_lu && <div className="claims">LRA {r.loudness_range_lu} LU</div>}
      </td>
      <td className="num">{signed(r.true_peak_dbtp, " dBTP")}</td>
      <td className="num">{r.clip_rate_pct && `${Number(r.clip_rate_pct).toFixed(3)}%`}</td>
    </tr>
  );
}

/** Claims under a measured value, each highlighted where it disagrees. */
function Claims({ items, hideSame = false }: { items: [string, string, boolean][]; hideSame?: boolean }) {
  const shown = items.filter(([, value, diff]) => value && (!hideSame || diff));
  if (!shown.length) return null;
  return (
    <div className="claims">
      {shown.map(([label, value, diff], i) => (
        <span key={label}>
          {i > 0 && " · "}
          <span className={diff ? "diff" : ""}>
            {label} {value}
          </span>
        </span>
      ))}
    </div>
  );
}

function Issues({ row }: { row: Row }) {
  const kinds = issues(row);
  if (!kinds.length) return <span className="muted">—</span>;
  return (
    <span className="issue-list">
      {kinds.map((k) => (
        <span key={k} className={`badge ${AUDIO_PROBLEMS.has(k) ? "issue-bad" : "issue-warn"}`}>
          {k}
        </span>
      ))}
    </span>
  );
}

/** One file, every aspect: what it measures, what its file says, what Rekordbox says. */
function Detail({ row: r }: { row: Row }) {
  const lossless = isLossless(r.codec);
  const sentences = r.flags ? r.flags.split("; ") : [];
  const rbNote = r.rb_match ? `matched by ${r.rb_match}` : "no row matched";

  const aspects: [string, string, string, string, { meta?: boolean; rb?: boolean }?][] = [
    ["Format", r.codec.toUpperCase(), r.encoder || "", ""],
    [
      "Bitrate",
      kbps(r.bitrate_kbps, true),
      [kbps(r.meta_bitrate_kbps, true), r.meta_bitrate_mode].filter(Boolean).join(" "),
      kbps(r.rb_bitrate_kbps, true),
      lossless
        ? {}
        : { meta: bitrateDiffers(r.meta_bitrate_kbps, r.bitrate_kbps), rb: bitrateDiffers(r.rb_bitrate_kbps, r.bitrate_kbps) },
    ],
    [
      "Sample rate",
      sampleRate(r.sample_rate),
      sampleRate(r.meta_sample_rate),
      sampleRate(r.rb_sample_rate),
      { meta: differs(r.meta_sample_rate, r.sample_rate), rb: differs(r.rb_sample_rate, r.sample_rate) },
    ],
    [
      "Bit depth",
      r.bit_depth ? `${r.bit_depth} bits used` : lossless ? "" : "n/a (lossy)",
      r.meta_bit_depth && `${r.meta_bit_depth}-bit`,
      r.rb_bit_depth && `${r.rb_bit_depth}-bit`,
      lossless ? { meta: differs(r.meta_bit_depth, r.bit_depth), rb: differs(r.rb_bit_depth, r.meta_bit_depth || r.bit_depth) } : {},
    ],
    [
      "Length",
      clock(num(r.duration_s), true),
      clock(num(r.meta_duration_s), true),
      clock(num(r.rb_duration_s)),
      {
        meta: farApart(r.meta_duration_s, r.duration_s, DURATION_TOLERANCE.meta),
        rb: farApart(r.rb_duration_s, r.duration_s, DURATION_TOLERANCE.rb),
      },
    ],
    ["ReplayGain", signed(r.replaygain_db, " dB"), signed(r.meta_replaygain_db, " dB"), ""],
    [
      "Spectrum",
      r.cutoff_khz ? `content to ${Number(r.cutoff_khz).toFixed(2)} kHz, ${r.cutoff_sharp === "yes" ? "then a cliff" : "soft roll-off"}` : r.bitrate_kbps ? "full band" : "",
      "",
      "",
    ],
    ["Loudness", r.integrated_lufs && `${r.integrated_lufs} LUFS integrated, LRA ${r.loudness_range_lu || "?"} LU`, "", ""],
    [
      "Peaks",
      [signed(r.true_peak_dbtp, " dBTP true"), signed(r.sample_peak_dbfs, " dBFS sample"), r.plr_db && `PLR ${r.plr_db} dB`]
        .filter(Boolean)
        .join(", "),
      "",
      "",
    ],
    [
      "Clipping",
      r.clipped_samples ? `${Number(r.clipped_samples).toLocaleString()} samples (${Number(r.clip_rate_pct).toFixed(4)}%)` : "",
      "",
      "",
    ],
    ["Channels", [r.channels, r.stereo_correlation && `correlation ${r.stereo_correlation}`].filter(Boolean).join(", "), "", ""],
    ["Decode errors", r.decode_errors, "", ""],
  ];

  return (
    <div className="quality-detail">
      <div className="toolbar">
        <span className="mono small" title={r.file_path}>
          {dirName(r.file_path)}
        </span>
        <span className="spacer" />
        <CopyButton text={r.file_path} label="Copy path" />
      </div>
      {r.error && <div className="error-box">{r.error}</div>}
      {sentences.length > 0 && (
        <ul className="flag-list">
          {sentences.map((s) => (
            <li key={s}>{s}</li>
          ))}
        </ul>
      )}
      <table className="table compare-table">
        <thead>
          <tr>
            <th />
            <th>Measured</th>
            <th>File metadata</th>
            <th>
              Rekordbox <span className="muted small">({rbNote})</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {aspects.map(([label, measured, meta, rb, diff = {}]) => (
            <tr key={label}>
              <th scope="row">{label}</th>
              <td>{measured}</td>
              <td className={diff.meta ? "diff" : ""}>{meta}</td>
              <td className={diff.rb ? "diff" : ""}>{rb}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Stat({ value, label }: { value: string; label: string }) {
  return (
    <div className="stat">
      <strong>{value}</strong>
      <span>{label}</span>
    </div>
  );
}

// --- values -------------------------------------------------------------------

function issues(r: Row): string[] {
  return r.issues ? r.issues.split("; ") : [];
}

function num(v: string | undefined): number | null {
  if (v === undefined || v === "") return null;
  const n = Number(v);
  return isFinite(n) ? n : null;
}

function numbers(rows: Row[], column: string): number[] {
  return rows.map((r) => num(r[column])).filter((v): v is number => v !== null);
}

/** Numeric order, smallest first, blanks last. */
function ascending(a: string, b: string): number {
  return numeric(a, b, (x, y) => x - y);
}

/** Numeric order, largest first, blanks still last. */
function descending(a: string, b: string): number {
  return numeric(a, b, (x, y) => y - x);
}

function numeric(a: string, b: string, order: (x: number, y: number) => number): number {
  const x = num(a);
  const y = num(b);
  if (x === null) return y === null ? 0 : 1;
  if (y === null) return -1;
  return order(x, y);
}

function isLossless(codec: string): boolean {
  return ["flac", "alac", "wavpack", "ape", "tta"].includes(codec) || codec.startsWith("pcm_");
}

function differs(claimed: string, measured: string): boolean {
  return !!claimed && !!measured && claimed !== measured;
}

function bitrateDiffers(claimed: string, measured: string): boolean {
  const c = num(claimed);
  const m = num(measured);
  return c !== null && m !== null && Math.abs(c - m) > BITRATE_TOLERANCE * m;
}

function farApart(claimed: string, measured: string, tolerance: number): boolean {
  const c = num(claimed);
  const m = num(measured);
  return c !== null && m !== null && Math.abs(c - m) > tolerance;
}

function kbps(v: string, unit = false): string {
  const n = num(v);
  if (n === null) return "";
  return `${Number.isInteger(n) ? n : n.toFixed(1)}${unit ? " kbps" : ""}`;
}

// Not toLocaleString: in a locale that groups thousands with a dot, 44100 Hz
// reads as "44.100 Hz", which looks like 44.1.
function sampleRate(v: string): string {
  const n = num(v);
  return n === null ? "" : `${Number((n / 1000).toFixed(2))} kHz`;
}

function signed(v: string, unit: string): string {
  const n = num(v);
  if (n === null) return "";
  return `${n > 0 ? "+" : ""}${v}${unit}`;
}
