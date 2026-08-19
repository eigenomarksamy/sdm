# CLAUDE.md

Guidance for Claude Code when working in this repository.

## What this repo is

`sdm` is a personal music-library toolchain for a DJ workflow, exposed as one
command with four isolated features over a shared core:

```text
sdm download   sdm catalog   sdm rekordbox   sdm quality
      \             |              |              /
       \____________ sdm.core ____________________/
```

## Layout

| Path | Purpose |
| --- | --- |
| `src/sdm/cli.py` | Top-level parser; each feature registers one subcommand |
| `src/sdm/core/` | Shared, dependency-light. Knows nothing about any feature |
| `src/sdm/features/spotify/` | `sdm download` — Spotify downloader |
| `src/sdm/features/catalog/` | `sdm catalog` — filesystem catalog + audit |
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

Each feature package exposes `add_parser(subparsers)` and sets
`handler=` via `set_defaults`; `cli.py` dispatches on it and returns its value
as the exit code.

## Commands

```ps1
pip install -e ".[all]"       # or .[rekordbox] / .[quality] / bare

sdm download --link "<spotify url>" --output "F:/Songs" --disable-gui
sdm catalog "C:\Users\omark\Music\postmodern"
sdm rekordbox --usb-path D:/ --output-dir ./out --duplicates-by-name
sdm quality "F:/Songs"
```

`pyproject.toml` is the only dependency manifest — there is no `requirements.txt`.

There is no test suite, linter config, or CI. Verify changes by running the
tools against a real folder or USB. A good regression check for `sdm catalog`
is to regenerate a CSV and diff it against a previous one; for
`sdm rekordbox`, `git worktree add` an older commit and diff the two exports on
identical inputs.

## `sdm.core`

- `track.py` — the one `Track` model (frozen dataclass) and `AUDIO_EXTS`.
  Readers convert Rekordbox ORM rows and tag objects into this so nothing
  downstream depends on pyrekordbox or mutagen types. Keep it that way.
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
- `report.py` — all CSV/JSON/sidecar writers. `newline=""` here is what stops
  the `csv` module writing blank lines between rows on Windows.

## Features

### `spotify`

`__init__.py` (parser) → `command.py` (builds `Cfg`, dispatches) → `runner.py`
(`run_cli`) → `api.py` (the real work: third-party download API, then re-tagging
with mutagen incl. embedded `APIC` cover art). `paths.py` has path resolution,
existing-file skipping, empty-file cleanup, and a SHA-256 duplicate finder.
`gui.py` / `osd.py` are the unwired Tkinter shell.

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

### `rekordbox`

**Read-only by design.** Never writes to the USB or the Rekordbox database;
output goes only to `--output-dir` or `--export-csv`. Preserve this.

- `reader.py` — three-tier source resolution: an explicit/USB `master.db`, then
  the **local** Rekordbox `master.db` (the only source with analyzed BPM and
  key, so it is preferred even when a USB is given, then scoped to the USB by
  filename via `_scope_to_usb`), then raw ID3 tags.
- `duplicates.py` — `find_duplicates_by_name` (normalized `(title, artist)`,
  needs no analysis data) and `find_duplicates` (prefilter buckets by quantized
  key/BPM/duration and checks the 8 neighbouring bins for tolerance edge cases;
  survivors confirmed by fingerprint, then linked with `UnionFind`).
- `fingerprint.py` — chromaprint via `fpcalc`; similarity is Hamming distance
  over decoded int32 subfingerprints.
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
