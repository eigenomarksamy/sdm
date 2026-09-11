# CLAUDE.md

Guidance for Claude Code when working in this repository.

## What this repo is

`sdm` is a personal music-library toolchain for a DJ workflow, exposed as one
command with four isolated features over a shared core:

```text
sdm download  sdm catalog  sdm duplicates  sdm rekordbox  sdm quality
      \            |             |               |            /
       \___________________ sdm.core ________________________/
```

## Layout

| Path | Purpose |
| --- | --- |
| `src/sdm/cli.py` | Top-level parser; each feature registers one subcommand |
| `src/sdm/core/` | Shared, dependency-light. Knows nothing about any feature |
| `src/sdm/features/spotify/` | `sdm download` — Spotify downloader |
| `src/sdm/features/catalog/` | `sdm catalog` — filesystem catalog + audit |
| `src/sdm/features/duplicates/` | `sdm duplicates` — duplicate scan over a music folder |
| `src/sdm/features/rekordbox/` | `sdm rekordbox` — Rekordbox reader + duplicate detection |
| `src/sdm/features/quality/` | `sdm quality` — real-vs-claimed bitrate check |
| `docs/rekordbox.md` | Detailed Rekordbox reference |
| `legacy/` | Superseded code, not imported, not expected to run |
| `deprecated/`, `out/`, `tmp/` | Untracked scratch (gitignored) |

## The two architectural rules

These are the point of the current structure. Breaking either undoes it.

1. **A feature may import from `sdm.core`. A feature must never import from a
   sibling feature.** If two features need the same thing, it goes in `core`.
2. **`add_parser` stays cheap — argparse only.** Third-party imports belong
   inside the command handler (see any `features/*/__init__.py`), so
   `sdm --help` and unrelated subcommands work without every optional
   dependency installed. `pyrekordbox`, `pyacoustid` and `pandas` are extras,
   not base dependencies.

Each feature package exposes `add_parser(subparsers, parents=())` and sets
`handler=` via `set_defaults`; `cli.py` dispatches on it and returns its value
as the exit code. `parents` carries the shared `--out-dir`/`--tmp-dir` parser so
those flags can be typed after the subcommand — pass it straight through to
`subparsers.add_parser(parents=list(parents))`.

## Commands

```ps1
pip install -e ".[all]"       # or .[rekordbox] / .[quality] / bare

sdm download --link "<spotify url>" --output "F:/Songs" --disable-gui
sdm catalog "C:\Users\omark\Music\postmodern"
sdm duplicates "F:/Songs"            # needs fpcalc on PATH
sdm duplicates "F:/Songs" --skip-fingerprint   # sizing run only, see below
sdm rekordbox --usb-path D:/ --duplicates-by-name
sdm quality "F:/Songs"
```

`pyproject.toml` is the only dependency manifest — there is no `requirements.txt`.
It does not tell the whole story though: fingerprinting needs the `fpcalc`
binary and `sdm quality` needs `ffprobe`/`ffmpeg`, neither of which pip can
install. Both are documented in a comment at the bottom of `pyproject.toml`.
pyacoustid is deliberately *not* a dependency — see `core/fingerprint.py`.

There is no test suite, linter config, or CI. Verify changes by running the
tools against a real folder or USB. A good regression check for `sdm catalog`
is to regenerate a CSV and diff it against a previous one; for
`sdm rekordbox`, `git worktree add` an older commit and diff the two exports on
identical inputs.

## `sdm.core`

- `track.py` — the one `Track` model (frozen dataclass), `AUDIO_EXTS`, and
  `iter_audio_files` (the one directory walk, kept beside the extension list so
  the two cannot drift; it also skips macOS AppleDouble `._Track.mp3` stubs,
  which match `AUDIO_EXTS` but are 4KB of resource-fork metadata — a USB that
  has been near a Mac is full of them, 192 of them on the test clone).
  Readers convert Rekordbox ORM rows and tag objects into
  `Track` so nothing downstream depends on pyrekordbox or mutagen types. Keep it
  that way.
- `text.py` — normalization. **Two strictnesses live here deliberately:**
  `normalize_loose` strips mix suffixes (catalog wants that; it only has tags to
  go on), `normalize_simple` does not (Rekordbox has BPM/key/duration to fall
  back on and errs toward keeping distinct releases distinct). They are in one
  file so the divergence is visible. Do not "unify" them without being asked.
- `tags.py` — `read_basic_tags` (eyed3, title/artist, reports errors) and
  `tracks_from_files` (mutagen, full `Track` incl. BPM/key/duration). Both are
  best-effort: unreadable tags yield "Unknown" rather than aborting.
- `grouping.py` — `UnionFind`, for collapsing pairwise matches into groups.
  Feature-specific group *construction* stays in the feature.
- `duplicates.py` — the two-stage detector (metadata prefilter → fingerprint
  confirm → union-find) and `find_duplicates_by_name`. Shared by `duplicates`
  and `rekordbox`. **Which prefilter dimensions are available depends on the
  source, so `require_bpm` and `key_must_match` are config, not assumptions:** a
  Rekordbox library has analyzed BPM and key for everything, a plain folder has
  only what the tags carry. Duration is the one dimension always present (it is
  decoded from the stream, not read from a tag), so it is always required and
  the others are opt-in. A non-required dimension is still used opportunistically
  when both tracks in a pair happen to have it.
- `fingerprint.py` — chromaprint via `fpcalc`; similarity is Hamming distance
  over the int32 subfingerprints. **It shells out to `fpcalc -raw -json` rather
  than using pyacoustid, and that is load-bearing.** `acoustid.fingerprint_file`
  returns the *compressed* base64 fingerprint, and decoding that back to
  integers goes through `chromaprint.py`, a ctypes wrapper around the native
  `libchromaprint` shared library — which the standalone `fpcalc.exe` does not
  ship. Installing fpcalc the obvious way therefore produced a tool that
  fingerprinted every track and then raised `ImportError: couldn't find
  libchromaprint` on the first comparison. `-raw` returns the integers directly,
  so comparing needs nothing that computing did not already require. Do not
  "modernize" this back onto pyacoustid.
  Unrelated tracks score ~0.5, not ~0: half the bits of two random 32-bit words
  agree by chance. That is why the threshold is 0.85 and not something near zero.
  A missing binary raises `RuntimeError`; a file that merely fails to decode
  returns `None`. Callers depend on that distinction.
- `report.py` — all CSV/JSON/sidecar writers. `newline=""` here is what stops
  the `csv` module writing blank lines between rows on Windows.
  `write_duplicate_report` is the shared duplicate CSV+JSON writer, so a folder
  scan and a Rekordbox run emit the same shape and can be diffed against each
  other.
- `paths.py` — the counterpart to `report.py`: `report` decides *how* a file is
  written, `paths` decides *where*. Two process-global roots, set once by
  `cli.py` from `--out-dir`/`--tmp-dir` (falling back to `SDM_OUT_DIR`/
  `SDM_TMP_DIR`, then `./out` and `./tmp`). `out_dir(feature)` gives
  `out/<feature>/`; `scratch(prefix)` is a context manager yielding a temp dir
  under `tmp/` that is removed on exit. **Nothing calls `scratch` yet** — no
  feature currently writes intermediates — it exists so that when one needs to,
  the scratch stays in the project rather than the system temp directory.
  `resolve_output(path, feature, default_name)` is the rule every output flag
  goes through: `None` → the default under `out/<feature>/`, a bare filename →
  that name under `out/<feature>/`, anything with a directory component → used
  verbatim. That last case is what keeps `--export-csv D:/x.csv` working, so
  preserve it. Stdlib only, so `add_parser` may import it.

## Features

### `spotify`

`__init__.py` (parser) → `command.py` (builds `Cfg`, dispatches) → `runner.py`
(`run_cli`) → `api.py` (the real work: third-party download API, then re-tagging
with mutagen incl. embedded `APIC` cover art). `paths.py` has path resolution,
existing-file skipping, empty-file cleanup, and a SHA-256 duplicate finder.
`gui.py` / `osd.py` are the unwired Tkinter shell.

Downloaded audio is **payload, not a report**, so `--output` is deliberately not
routed through `core.paths` — it goes where the user points it. What *is* routed
there is the log: `command.py` now configures the root logger at
`out/logs/download.log` (unless `--disable-log`), which is what finally gives
the long-dead `logging.error`/`logging.info` calls in `api.py` and `runner.py`
somewhere to land.

**Pre-existing bugs — expected, not yours to fix on sight:**

- `command.py` — the GUI branch is `pass`, so `--disable-gui` is required for
  the command to do anything. `run()` returns `None`, so the exit code is
  always 0.
- `__init__.py` — `--sync` and `--run-pp` are parsed but never read.
- `api.py` — `SpotifyDownloadManager.DOWNLOAD_API` points at
  `api.spotidownloader.com` but `get_playlist_info` hardcodes
  `api.spotifydown.com`. Both are third-party services and the most likely
  cause of runtime breakage.
- `gui.py` — the progress bar is a cosmetic `sleep` loop that reaches 100%
  before the download starts, and it calls `run_gui(cfgObj, [url])` against a
  signature of `run_gui(link, conf)` — arguments reversed. `osd.run_gui` is a
  no-op stub, so nothing surfaces.

### `catalog`

One run does three things (`exporter.run`): export with a path sidecar, report
duplicates, then cross-validate by re-walking the directory and set-diffing it
against the sidecar. **The sidecar and the cross-validation are the point** —
this is an auditable export, not a dump. Preserve that property.

Handles `.mp3` only, not the full `AUDIO_EXTS` set.

**Pre-existing bug — pass Windows-style paths.** The sidecar records
`os.path.join(root, filename)`, which keeps whatever separator style you typed,
but `validate_mp3_csv` compares against `os.path.abspath(...)`, which normalizes
to backslashes. So `sdm catalog "C:/Users/.../postmodern"` reports every file as
both missing and extra (`is_valid: False`), while
`sdm catalog "C:\Users\...\postmodern"` reports `is_valid: True`. Same in the
pre-refactor code. If cross-validation reports a total mismatch, check the path
style before hunting for a real fault.

### `duplicates`

`__init__.py` (parser) → `command.py`: walk the folder, read tags, run
`core.duplicates`, write the shared report to `out/duplicates/`. Read-only — it
reports, it never moves or deletes a file. The whole feature is ~70 lines
because the detector is in `core`; what it owns is the *defaults*, and those are
the point.

**Why the defaults differ from `rekordbox`.** A folder has no analysis data, so
BPM and key are usually absent from the tags. Requiring them would silently drop
most of the library, so the prefilter keys on duration alone by default and the
fingerprint does the deciding. `--require-bpm` / `--require-key` are there for
libraries known to be fully tagged, and are much faster.

**`--skip-fingerprint` is a sizing tool, not an answer.** Duration-only
bucketing is deliberately permissive: on a 3,459-track folder it produced 57,176
candidate pairs which union-find then chained into one group of 3,297. Use it to
see how big a run will be; do not read its groups as duplicates.

The run fingerprints every eligible track once. `command.py` pre-flights
`PREFLIGHT_TRACKS` files first — without `fpcalc` every pair is dropped and the
run would otherwise end with a meaningless "0 duplicate groups". More than one
file is tried so a single corrupt track cannot abort a healthy run.

**Measured baseline** (`test-sdm-lib-clone/pioneer-usb-full-clone`, 3,664 files):
9m12s wall, 64,272 candidate pairs, 178 confirmed, **158 groups** (148 pairs, 10
triples), 9 tracks unfingerprintable. Fingerprinting runs ~0.14s/track and is
the bulk of the time. Widest duration spread inside any group was 0.84s, and the
groups included an mp3/flac pair and several same-audio/different-filename hits
— the cases a hash or a filename match would both miss. Use these numbers as the
regression check: a run on this folder that reports far more or far fewer groups
means something changed.

### `rekordbox`

**Read-only by design.** Never writes to the USB or the Rekordbox database;
output goes only to `--output-dir` or `--export-csv`. Preserve this.

- `reader.py` — three-tier source resolution: an explicit/USB `master.db`, then
  the **local** Rekordbox `master.db` (the only source with analyzed BPM and
  key, so it is preferred even when a USB is given, then scoped to the USB by
  filename via `_scope_to_usb`), then raw ID3 tags.
- Detection itself lives in `core/duplicates.py` and `core/fingerprint.py` —
  shared with `sdm duplicates`, so a change there affects both. This feature
  supplies the track list and the config (BPM and key required, because a
  Rekordbox library has them).
- `analysis.py` — hand-rolled binary parser for Rekordbox v5 `USBANLZ/*.2EX`
  files. **Not imported anywhere.** Research code, kept because the exported
  `export.pdb` / `exportLibrary.db` are encrypted DeviceSQL and unreadable by
  pyrekordbox. Do not wire it in without being asked.

Note `_artist_name_v6` returns `""` when the local database has no linked
artist row, which is common — so a local-DB-only export has blank artists and
`--duplicates-by-name` is correspondingly weak. Attaching the USB brings the ID3
fallback into play and fills them in.

### `quality`

Thin wrapper over `analyzer.compare_and_report`, which shells out to
`ffprobe`/`ffmpeg`. Returns a pandas DataFrame; the handler prints or writes it.

`--output-csv` requires a value here, while `rekordbox --export-csv` accepts the
bare flag. That asymmetry is deliberate: this parser has a positional
`directory`, and an `nargs="?"` flag would swallow it — `sdm quality
--output-csv F:/Songs` would read the folder as the CSV name and then fail for
a missing directory. `rekordbox` has no positional, so it is safe there.

## Conventions

- Windows-first. Paths in examples use drive letters; PowerShell is the shell.
- `core/` and the feature `__init__`/`command` modules use
  `from __future__ import annotations`, type hints, and module docstrings that
  explain *why*. Match that there.
- Code moved from the old layout (`api.py`, `runner.py`, `paths.py`,
  `exporter.py`) is looser and untyped. Match the surrounding file rather than
  upgrading it in place.
- Progress is reported by passing a `progress`/`log` callable, not by printing
  from library code. Keep `print` in `command.py` / handlers.
- `.gitignore` excludes `*.csv`, `*.txt`, `out/`, `tmp/`, `deprecated/`, and
  `sync*.json`. **No CSV or TXT file in this repo is tracked** — every catalog
  export, report and sidecar you see is a local artifact.
