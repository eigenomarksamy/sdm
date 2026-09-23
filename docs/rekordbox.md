# `sdm rekordbox`

Reference for the Rekordbox feature: a read-only tool for inspecting a Rekordbox library and finding duplicate tracks.
It reads the Rekordbox database for the canonical track list and analysis
(BPM, key, duration), and can export that metadata to CSV or report duplicates
either by name or by audio fingerprint.

> **Read-only by design.** This tool never writes to the USB or to the
> Rekordbox database. Output files (CSV + JSON reports) are written to a
> separate output directory you choose.

## What it does

Three independent modes (pick one per run):

1. **Export to CSV** (`--export-csv`) — dump every track's `title, artist, bpm,
   time, key` to a CSV file and exit.
2. **Duplicate report by name** (`--duplicates-by-name`) — group tracks that
   share the same `(title, artist)`. Needs no analysis data, so it covers every
   track including those without BPM/key.
3. **Duplicate report by audio** (default) — a two-stage analysis-based detector
   (see below).

## Where the data comes from

When you point the tool at a USB, it resolves the track list in this order:

1. A `master.db` given directly via `--db-path`, or one found on the USB.
2. The **local Rekordbox `master.db`** (pyrekordbox auto-locates it). This is the
   only source that carries the analyzed BPM and key, so it is preferred even
   when a USB is supplied. With `--usb-path`, the result is then scoped to the
   tracks actually on the USB (matched by filename), and any USB files missing
   from the local database are filled in from their ID3 tags (BPM/key may be
   blank for those).
3. **ID3 tags** from the USB's `Contents/` folder — last resort, used only if the
   local database can't be opened. BPM/key are sparse here because Rekordbox
   stores analysis in its database, not in the audio files.

> The exported USB databases (`export.pdb` / `exportLibrary.db`) are encrypted
> DeviceSQL and are **not** readable by the installed pyrekordbox, so they are
> skipped automatically.

## How audio-based duplicate detection works

Two-stage, to keep fingerprinting cheap:

1. **Prefilter** — group tracks whose BPM, key, and duration fall inside the
   configured tolerances. Cheap, narrows the candidate pairs drastically.
2. **Confirm** — compute a chromaprint fingerprint for each track in a candidate
   group and compare pairwise. Pairs above the similarity threshold are linked
   into a duplicate group via union-find.

The CSV/JSON output records which rule(s) matched for each group
(`metadata`, `fingerprint`, or — in name mode — `title+artist`).

## Setup

1. Install the optional dependencies for this feature (`pyrekordbox`,
   `pyacoustid`):

   ```ps1
   pip install -e ".[rekordbox]"
   ```

2. (Audio mode only) Install `fpcalc` (chromaprint) and put it on PATH. Download
   the Windows build from <https://acoustid.org/chromaprint> and unzip somewhere
   on PATH, or pass `--fpcalc-path` at runtime.

3. Rekordbox must be (or have been) installed on this machine. `pyrekordbox`
   extracts the SQLCipher key for `master.db` from your local Rekordbox config.
   If it can't find the key, run:

   ```ps1
   python -m pyrekordbox download-key
   ```

## Usage

With the USB mounted at `D:/`:

### Export track metadata to CSV

```ps1
sdm rekordbox --usb-path D:/ --export-csv library_with_analysis.csv
```

Writes one row per track (`title, artist, bpm, time, key`) and exits.

### Duplicate report by title + artist

```ps1
sdm rekordbox --usb-path D:/ --output-dir ./out --duplicates-by-name
```

Groups tracks with the same `(title, artist)`. Title and artist are normalized
(lowercased, surrounding/duplicate whitespace collapsed) before matching, so
`"Aquarius"` matches `"aquarius "` but **not** `"Aquarius (Extended Mix)"`.

### Duplicate report by audio fingerprint (default)

```ps1
sdm rekordbox --usb-path D:/ --output-dir ./out
```

Or skip the fingerprint stage for a fast, prefilter-only pass (also useful when
`fpcalc` isn't installed yet):

```ps1
sdm rekordbox --usb-path D:/ --output-dir ./out --skip-fingerprint
```

### Point at a database directly

```ps1
sdm rekordbox --db-path "C:/path/to/master.db" --output-dir ./out
```

## Options

| Flag | Default | Meaning |
| --- | --- | --- |
| `--usb-path` | — | Mount path of the Rekordbox USB (e.g. `D:/`). |
| `--db-path` | — | Direct path to a `master.db` (overrides `--usb-path`). |
| `--output-dir` | `./out` | Where to write duplicate reports. |
| `--export-csv PATH` | — | Export track metadata to `PATH` and exit. |
| `--duplicates-by-name` | off | Report duplicates by `(title, artist)`; skips the audio pipeline. |
| `--bpm-tolerance` | `0.5` | BPM diff allowed in the audio prefilter. |
| `--duration-tolerance` | `2.0` | Seconds of duration diff allowed in the audio prefilter. |
| `--no-key-match` | off | Do **not** require the Rekordbox key to match in the audio prefilter. |
| `--fingerprint-threshold` | `0.85` | Min chromaprint similarity (0..1) to confirm a duplicate. |
| `--skip-fingerprint` | off | Skip the fingerprint stage; report on the metadata prefilter alone. |
| `--fpcalc-path` | — | Path to the `fpcalc` binary if it isn't on PATH. |

## Output

The two duplicate-report modes write to `--output-dir`:

- `duplicates.csv` — one row per track inside a duplicate group, with the group
  ID and the rule(s) that matched.
- `duplicates.json` — same data, machine-readable, with full per-track fields.

Export mode (`--export-csv`) instead writes a single CSV to the path you give and
produces no `duplicates.*` files.
