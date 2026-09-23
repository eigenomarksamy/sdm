# CLAUDE.md

Guidance for Claude Code when working in this repository.

## What this repo is

`sdm` is a personal music-library toolchain for a DJ workflow, exposed as one
command with five isolated features over a shared core:

```text
sdm catalog  sdm duplicates  sdm rekordbox  sdm analyze  sdm quality
     \             |               |             |           /
      \________________________ sdm.core ____________________/

sdm download — deprecated, not registered (features/spotify)
```

**`sdm download` is switched off.** `spotify` is not in `FEATURES` in `cli.py`,
so the subcommand does not exist: it is absent from `sdm --help`, and `cli.py`'s
`DEPRECATED_COMMANDS` intercepts the name before argparse so it reports being
disabled rather than "invalid choice". The package is otherwise untouched and
still imports cleanly. Re-enable by restoring the import and the `FEATURES`
entry and removing the `DEPRECATED_COMMANDS` row — three lines, one file.
**Do not delete `features/spotify/`, and do not fix its bugs on sight;** it is
parked, not condemned.

## Layout

| Path | Purpose |
| --- | --- |
| `src/sdm/cli.py` | Top-level parser; each feature registers one subcommand |
| `src/sdm/core/` | Shared, dependency-light. Knows nothing about any feature |
| `src/sdm/features/spotify/` | `sdm download` — Spotify downloader. **Deprecated: not registered in `cli.py`, so the command does not exist.** Code kept as-is |
| `src/sdm/features/catalog/` | `sdm catalog` — filesystem catalog + audit |
| `src/sdm/features/duplicates/` | `sdm duplicates` — duplicate scan over a music folder |
| `src/sdm/features/rekordbox/` | `sdm rekordbox` — Rekordbox reader + duplicate detection |
| `src/sdm/features/analyze/` | `sdm analyze` — beat grids + phrase structure off a Pioneer USB |
| `src/sdm/features/quality/` | `sdm quality` — real-vs-claimed bitrate check |
| `docs/rekordbox.md` | Detailed Rekordbox reference |
| `docs/analyze.md` | Detailed ANLZ / phrase-analysis reference |
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

sdm catalog "C:\Users\omark\Music\postmodern"
sdm duplicates "F:/Songs"            # needs fpcalc on PATH
sdm duplicates "F:/Songs" --skip-fingerprint   # sizing run only, see below
sdm rekordbox --usb-path D:/ --duplicates-by-name
sdm analyze D:/                      # beat grids + phrases, no database needed
sdm quality "F:/Songs"
```

`pyproject.toml` is the only dependency manifest — there is no `requirements.txt`.
It does not tell the whole story though: fingerprinting needs the `fpcalc`
binary and `sdm quality` needs `ffprobe`/`ffmpeg`, neither of which pip can
install. (`sdm duplicates` borrows a temporary `fpcalc` when none is
installed — see `core/fpcalc_fetch.py` — but `sdm rekordbox` does not.) Both are documented in a comment at the bottom of `pyproject.toml`.
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
- `tags.py` — `read_basic_tags` (eyed3, title/artist, reports errors),
  `tracks_from_files` (mutagen, full `Track` incl. BPM/key/duration) and
  `read_title_artist` (mutagen, two fields for one file). All three are
  best-effort: unreadable tags yield "Unknown" rather than aborting.
  **The third is not redundant with the other two**, which is why `analyze` did
  not just call one of them: `read_basic_tags` is eyed3 and therefore mp3-only,
  and `tracks_from_files` is batch-shaped and *drops* files whose duration it
  cannot read — correct for the duplicate prefilter, wrong for a caller that
  needs a name on every row. It goes through `_tag` like the others, so it
  cannot repeat the FLAC bug below.
  **Do not reintroduce a per-container branch here.** `tracks_from_files` used
  to pick an ID3 path vs a Vorbis path on `hasattr(tags, "get")` — but *every*
  mutagen tag object has `.get`, so FLAC and OGG took the ID3 path, where
  `TBPM`/`TKEY` do not exist and the Vorbis lookups were dead code. Every FLAC
  in a library came out with no BPM, no key, and a title stringified straight
  from the list mutagen returns (`"['Somefunkydrum']"`), which also broke name
  matching against the same track's mp3. `_tag` now tries each field's ID3,
  Vorbis and MP4 spelling in turn; the names do not collide across formats, so
  the first hit is right and no sniffing is needed. `_first` is the other half:
  Vorbis values are lists, ID3 values are frames.
  A BPM tag of `0` is read as absent — a placeholder would otherwise satisfy
  `require_bpm` and then compare against nothing.
- `anlz.py` — reads Rekordbox's own analysis (beat grid, phrase structure) out
  of the `PIONEER/USBANLZ/` files on a Pioneer USB. Backs `sdm analyze`; see
  `docs/analyze.md`. **It walks the ANLZ tag chain and parses one tag at a time
  instead of calling `AnlzFile.parse_file`, and both halves of that are
  load-bearing.** *Selective*, because waveform tags are almost all of the bytes
  and nothing renders them — parsing only `ANALYSIS_TAGS` takes a full-library
  scan from 8m28s to 49s. *One tag at a time*, because pyrekordbox parses a file
  as a single construct `Struct`, so one tag it dislikes loses the whole file:
  `PQTZ` declares its second header word `Const(0x00080000)` when only the high
  half is fixed, which discarded 119 of 3,665 beat grids, and newer Rekordbox
  emits `PVDI`/`PVB2` tags it has never seen. The binary layouts still come from
  `pyrekordbox.anlz` — this module never re-describes them, it chooses which to
  parse and survives the ones that fail. Key is *not* in ANLZ (database only),
  and cue points are deliberately unparsed: the reference USB has one hot cue in
  3,665 tracks, so a cue reader would be untested code serving nothing.
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
- `fpcalc_fetch.py` — the escape hatch for the one dependency pip cannot
  install. `borrowed_fpcalc()` is a context manager: it yields an already
  installed fpcalc if there is one (downloading nothing), otherwise it fetches
  the pinned Chromaprint release archive into a `paths.scratch` under `tmp/`,
  unpacks the binary, checks it actually runs, and yields that — **and a
  `finally` deletes it when the block exits, on success, on error and on Ctrl-C
  alike.** That `finally` is `_purge`, not `paths.scratch`'s own removal, and
  the difference is load-bearing on Windows: `scratch` removes with
  `ignore_errors=True`, and after a long run the just-executed `.exe` can still
  be held open (a scanner reading the image it watched run), so `rmtree` loses
  on a sharing violation and says nothing. A full-library run leaked exactly one
  scratch that way. `_purge` retries for a few seconds and, if it still cannot,
  says so. Borrowed, not installed: nothing touches PATH, so a user
  who minds re-downloading ~2 MB per run should install fpcalc properly, which
  is detected first and skips all of this. Stdlib only (`urllib`, `zipfile`,
  `tarfile`), because the thing that makes fingerprinting possible must not
  itself need a dependency that is missing. `CHROMAPRINT_VERSION` is pinned
  rather than resolved from the "latest release" API so a run cannot silently
  change binaries.
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
  under `tmp/` that is removed on exit. `core/fpcalc_fetch.py` is its one
  caller, and shows what the in-project location buys: a hard kill that no
  `finally` survives leaves the debris somewhere visible and already gitignored,
  rather than in the system temp directory.
  `resolve_output(path, feature, default_name)` is the rule every output flag
  goes through: `None` → the default under `out/<feature>/`, a bare filename →
  that name under `out/<feature>/`, anything with a directory component → used
  verbatim. That last case is what keeps `--export-csv D:/x.csv` working, so
  preserve it. Stdlib only, so `add_parser` may import it.

## Features

### `spotify` — deprecated, disabled

**Not reachable.** `cli.py` does not register it, so nothing below can be run
today; it is documented because the code is still here and the feature is parked
rather than deleted. Treat everything in this section as reference for a future
re-enable, and leave the package alone unless the task is that re-enable.

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
- `__init__.py` — `--sync` and `--run-pp` are parsed but never read. `--dry-run`
  and `--pre-order` get one step further and are worse for it: `command.py`
  passes both into `Cfg`, and nothing in `api.py` or `runner.py` ever consults
  `cfg.dry_run` or `cfg.pre_order`. **`--dry-run` does not simulate anything —
  it downloads.**
- `paths.py` — `find_and_delete_duplicates` is never called by anything, and
  prompts with `input()`, so it could not be called from a normal run anyway.
  `sdm duplicates` is the real answer to that problem. Deletion candidate.
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

`exporter.run` returns 0 unconditionally, including when `validate_mp3_csv`
reports `is_valid: False` — the audit is printed, never signalled. A script
cannot currently gate on it.

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

**Measured tag coverage** on the test clone (3,664 files), so "usually absent"
has a number: BPM 1,814 (50%), key 3,656 (99.8%). Blank BPM columns in the
report are the files, not the reader — it extracts every `TBPM` frame present.
The report skews further (10% of its rows carry BPM) because duplicate groups
are mostly album rips, which are the tracks least likely to have been
DJ-analyzed. `--require-key` is therefore nearly free on this library while
`--require-bpm` would discard half of it.

**`--skip-fingerprint` is a sizing tool, not an answer.** Duration-only
bucketing is deliberately permissive: on a 3,459-track folder it produced 57,176
candidate pairs which union-find then chained into one group of 3,297. Use it to
see how big a run will be; do not read its groups as duplicates.

The run fingerprints every eligible track once. `command.py` pre-flights
`PREFLIGHT_TRACKS` files first — without `fpcalc` every pair is dropped and the
run would otherwise end with a meaningless "0 duplicate groups". More than one
file is tried so a single corrupt track cannot abort a healthy run. The
pre-flight swallows the `RuntimeError` that `compute` raises for a missing
binary: at that one point "no binary" and "nothing fingerprinted" are the same
answer, and that is what keeps a missing fpcalc an error message rather than a
traceback.

`fpcalc` no longer has to be installed. The whole detection runs inside
`core.fpcalc_fetch.borrowed_fpcalc`, which uses an installed binary if there is
one and otherwise downloads a temporary one into `tmp/` for the run and deletes
it afterwards. `--no-fetch-fpcalc` opts out and fails instead. The binary is
resolved once for the run, so **everything that fingerprints must stay inside
that `with` block** — leaving it deletes the binary. `sdm rekordbox` is not
wired to it yet and still needs fpcalc on PATH.

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
- `analysis.py` — hand-rolled binary parser for `USBANLZ` files. **Not imported
  anywhere, superseded by `core/anlz.py`, and wrong.** It searches for `PSGL` and
  `PKEY` tags; neither exists in the ANLZ format (the real tags are `PPTH`,
  `PQTZ`, `PQT2`, `PVBR`, `PCOB`, `PCO2`, `PWAV`/`PWV2`–`PWV7`, `PWVC`, `PSSI`),
  and its BPM extractor brute-forces byte offsets until a float lands between 40
  and 200. Do not treat it as a reference for the format or wire it in — use
  `core/anlz.py`. It is a deletion candidate.

Note `_artist_name_v6` returns `""` when the local database has no linked
artist row, which is common — so a local-DB-only export has blank artists and
`--duplicates-by-name` is correspondingly weak. Attaching the USB brings the ID3
fallback into play and fills them in.

### `analyze`

`__init__.py` (parser) → `command.py`: stream `core.anlz.read_usb` and write the
reports. **Read-only**, like `rekordbox` — it opens the USB's analysis files and
writes nowhere near them. See `docs/analyze.md` for the format details.

The one thing it answers that nothing else can: **what Rekordbox worked out**
about a track, as opposed to what the library contains. Beat grid and phrase
structure live only in `PIONEER/USBANLZ/`, not in the tags and not in the
exported database — so this is also the only feature that needs no Rekordbox
install and no `master.db`, which is exactly where `sdm rekordbox` is weakest.

**Title and artist are the one thing in the report that is not from ANLZ.** The
format records a path, never a name, so `command.py` reads them from the audio
file's tags via `core.tags.read_title_artist` — only for tracks whose file
resolved, "Unknown" for a file that carries none (38 of 3,665, all untagged WAV
and AIFF). This does not compromise the no-database property and costs about a
second: mutagen reads the tag header, not the audio.

**The command streams rather than collects, and that is the design.** A library's
beat grids are millions of `Beat` objects; rows are written as tracks are read,
which is why `--export-beats` costs disk and not memory. `read_usb(with_beats=)`
exists for the same reason — the summary fields (BPM, first downbeat, variable
tempo) are computed during the parse so the grid itself never has to be kept.

**Phrase labels depend on the mood**, which is why `_phrase_label` takes it: mid
and low moods name phrases by kind alone (Intro, Verse 1–6, Bridge, Chorus,
Outro), while high mood uses fewer kinds and carries the variant in separate flag
fields (`k1` picks the second Intro/Chorus/Outro, `k2`/`k3` pick which Up). That
is 20 labels, and all 76,118 phrases on the reference USB resolve to one — an
unrecognized kind is reported as `Unknown (mood M, kind K)` rather than given a
plausible name, so a format change surfaces in the output.

**Measured baseline** (`test-sdm-lib-clone/pioneer-usb-full-clone`, 3,665
tracks): 49s wall warm / ~1m15s cold, beat grid 3,655 (99.7%), phrases 3,646 (99.5%), 76,118
phrases, moods high 2,314 / mid 1,251 / low 81, 2 variable-tempo tracks, 119
recovered beat grids, 0 unknown labels. Use these as the regression check.

Worth knowing why the grid BPM matters: on the 1,814 tracks carrying a `TBPM`
tag, 17.3% disagree with the grid by more than 0.5 BPM — 97 of them tagged at
exactly half the real tempo. The grid is a measurement; the tag is a claim.

### `quality`

Thin wrapper over `analyzer.compare_and_report`, which shells out to
`ffprobe`/`ffmpeg`. Returns a pandas DataFrame; the handler prints or writes it.

**Pre-existing bug — the bitrate comparison is meaningless, and it is the
headline feature.** `compute_audio_properties` decodes the file to 16-bit
stereo PCM and divides the byte count by the duration, which is
`sample_rate * 32` for every file however it was encoded — a 128 kbps rip and a
true 320 both come out at ~1,411 kbps. It is then subtracted from
`eyed3`'s `info.bit_rate[1]`, which is in *kbps*, so the two operands are also
1000x apart. The sample-rate half of the report is sound. Fixing this is the
starting point of the planned `quality` work below, not a side quest: the real
measurement is `ffprobe`'s stream bitrate plus a spectral cutoff check, not a
decode-and-divide.

`compare_and_report` uses `os.listdir` and an `endswith('.mp3')` test, so it is
top-level-only and mp3-only — the one feature that does not use
`core.track.iter_audio_files`.

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

## Planned work

Five features are designed but **not implemented** — see the "Ideas" section at
the end of `README.md` for what each one is and why. Nothing named there exists
in the tree; do not read a mention of one as a module to import or extend.

1. **Library manager** — Rekordbox playlists, bulk tag/metadata edits, analysis
   import/export. New feature package; playlists first, because they are plain
   `master.db` rows and need no new format work.
2. **Deeper `sdm quality`** — true bitrate and transcode detection, clipping,
   EBU R128 loudness, diffed against the tags and the database. This one
   **extends the existing `quality` feature**; it is not a new command.
3. **Serato / Traktor export** — one-way, onto a differently formatted USB.
4. **`sdm dig`** — finds records *not* in the library, from seeds (genre, style,
   artist, track, label, era, BPM/key) tuned by underground level and source,
   then filtered against what is already owned.
5. **Genre/style enrichment** — fills in what the local library's tracks
   actually are, from Discogs styles, Last.fm tags and MusicBrainz. **Build this
   before `dig`:** scoring a result as a percentile within its genre requires
   knowing the genre of the owned tracks it is being compared against.

What is already decided, and what the existing structure forces:

- **The first two features here write; `rekordbox` and `analyze` do not, and
  that does not change.** Every writer is its own feature with its own command,
  so a bug in one cannot be reached from a command whose contract is that it
  touches nothing. A writer backs up `master.db` first and refuses to run while
  Rekordbox holds it open.
- Serato needs `GEOB` frames written into the audio files themselves. **Nothing
  in this toolchain modifies an audio file today** except `sdm download`, on
  files it just created — treat that as new ground, not as an extension of
  anything.
- The manager will want readers `rekordbox` already has (`reader.py`'s source
  resolution) and `analyze` already has (`core/anlz.py`). Rule 1 applies: shared
  pieces move to `core` first, they are never imported across features.
- New dependencies stay extras, behind the handler, per rule 2 — Rekordbox
  writes via `pyrekordbox`, transcode detection via whatever does the FFT.
  `sdm --help` must keep working with none of them installed.
- **`dig` breaks assumptions the other five share, so do not model it on them.**
  It is network-first, so its results are not reproducible from local inputs; it
  needs credentials, which nothing here handles today (environment variables,
  never committed, and degrade to the sources that have keys rather than
  failing); and it needs a *persistent* cache, which neither `out/` (reports)
  nor `tmp/` (deleted on exit) is. Settle that third location before writing
  code. Each source is an adapter behind one interface, because most of the
  interesting ones are gated or closed — see the source table in `README.md`,
  and re-verify it, since the access rules move. It stays read-only against
  every service: it queries and reports, and never posts or follows.
