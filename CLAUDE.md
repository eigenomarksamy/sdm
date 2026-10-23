# CLAUDE.md

Guidance for Claude Code when working in this repository.

## What this repo is

`sdm` is a personal music-library toolchain for a DJ workflow, exposed as one
command with seven isolated features over a shared core:

```text
sdm catalog  sdm duplicates  sdm rekordbox  sdm analyze  sdm quality
     \             |               |             |           /
      \________________________ sdm.core ____________________/
                                /        \
               sdm playlist-diff          sdm playlist-export

sdm download — deprecated, not registered (features/spotify)
sdm web      — a front end over all of the above, beside cli.py (sdm.web)
browser      — a third front end: catalog, analyze, playlist-diff, playlist-export
               running in a browser tab via Pyodide, at sdm.eigenomar.com
               (sdm.browser)
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
| `src/sdm/features/quality/` | `sdm quality` — audio measured (bitrate, transcode cutoff, loudness, peaks, clipping) beside what tags and Rekordbox claim |
| `src/sdm/features/playlist_diff/` | `sdm playlist-diff` — Spotify playlist tracks a folder does not have. **Not** related to `features/spotify/` and imports nothing from it |
| `src/sdm/features/playlist_export/` | `sdm playlist-export` — a Spotify playlist to CSV. Same: unrelated to `features/spotify/` |
| `src/sdm/web/` | `sdm web` — local web UI. **A front end like `cli.py`, not a feature**; imports no feature. Stdlib only |
| `src/sdm/web/static/` | The built page. Gitignored, written by `npm run build` in `frontend/` |
| `frontend/` | The page's source: React 19 + TypeScript 7 + Vite 8. `package-lock.json` is committed, `node_modules/` is not |
| `src/sdm/browser.py` | The browser build's Python half. **A front end like `cli.py` and `sdm.web`, not a feature**; imports no feature |
| `frontend/src/browser/` | The browser build's page side: the API swapped in for `src/api.ts`, the Pyodide worker, the Spotify login, `_headers` |
| `build_browser.py` | Builds the browser version into `dist/` (gitignored): page, self-hosted Pyodide, wheels |
| `wrangler.jsonc` | Cloudflare Workers config serving `dist/` at sdm.eigenomar.com. `.wrangler/` is its gitignored state |
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
   dependency installed. `pyrekordbox` and `numpy` are extras,
   not base dependencies.

**`sdm.web` is not an exception to rule 1, because it is not a feature.** It
drives every command, which no feature may do, so it sits beside `cli.py` in
`cli.FRONTENDS` rather than in `FEATURES` — and even so it imports no feature:
it reads the parser, runs subprocesses, and reads report files. Keep it that
way; a web view that needs a feature's logic means that logic moves to `core`.
**`sdm.browser` is the same kind of thing** — a front end that runs commands
through `cli.main` and reuses `web/schema.py` and `web/reports.py` — and is
held to the same rule. It is not in `cli.FRONTENDS`: it is no subcommand, only
the module the browser build's worker imports.

Each feature package exposes `add_parser(subparsers, parents=())` and sets
`handler=` via `set_defaults`; `cli.py` dispatches on it and returns its value
as the exit code. `parents` carries the shared `--out-dir`/`--tmp-dir` parser so
those flags can be typed after the subcommand — pass it straight through to
`subparsers.add_parser(parents=list(parents))`.

## Commands

```ps1
pip install -e ".[all]"       # or .[rekordbox] / .[quality] / bare

sdm catalog "C:\Users\omark\Music\postmodern"
sdm catalog "F:\Songs" --missing-metadata   # tracks lacking a title/artist
sdm duplicates "F:/Songs"            # needs fpcalc on PATH
sdm duplicates "F:/Songs" --skip-fingerprint   # sizing run only, see below
sdm rekordbox --usb-path D:/ --duplicates-by-name
sdm analyze D:/                      # beat grids + phrases, no database needed
sdm quality "F:/Songs"               # measured vs claimed, -> out/quality/quality_Songs.csv
sdm quality D:/ --limit 50           # a USB; sample before the ~1 h full run
sdm playlist-diff "<spotify playlist link>" "F:\Songs"   # needs $SDM_SPOTIFY_CLIENT_ID
sdm playlist-diff "D:\export.csv" "F:\Songs"             # CSV export: no account needed
sdm playlist-export "<spotify playlist link>"            # -> out/playlist-export/<name>.csv

cd frontend; npm install; npm run build   # builds the page into src/sdm/web/static/
sdm web                                   # http://127.0.0.1:8770, opens the browser

python build_browser.py                   # the browser build -> dist/ (npm ci, Pyodide, wheels)
python build_browser.py --no-install      # same, skipping npm ci
npx wrangler dev                          # serves dist/ with _headers, http://127.0.0.1:8787
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
  `read_title_artist_raw` is the fourth, and `read_title_artist` is now a thin
  wrapper over it: same read, but None for an absent field plus an error
  string for an unreadable file. It exists for `catalog --missing-metadata`,
  which cannot use "Unknown" — a track tagged with the literal artist "Unknown"
  (there is one on the test clone, a vinyl-only white label) would be reported
  as untagged, and a corrupt file as merely untagged.
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
  **Multi-value fields are joined with `/` (`MULTI_VALUE_SEP`), not NUL.**
  ID3v2.4 lets one frame hold several values, and mutagen and eyed3 both
  stringify them NUL-joined — 233 artist tags on the test clone, all ID3. The
  NUL reached every report, and `playlist-diff` (which splits artists on `/`)
  saw "Delano Smith\x00Brian Kage" as one unknown artist and reported an owned
  track missing. `_first` joins frames, `read_basic_tags` re-joins eyed3's
  strings. Vorbis/MP4 lists still take the first value; the clone has no
  multi-value ones to test a join against.
  **`_tag` skips a name the container rejects, and that is load-bearing too.**
  Vorbis comments only allow ASCII keys, so `tags.get("\xa9ART")` on a FLAC
  *raises* `ValueError` — and the lookup only reaches the MP4 spelling when the
  field is absent. Uncaught, any FLAC/OGG missing a title or artist lost its
  whole read: "Unknown" for both fields in `analyze`, no BPM or key in
  `duplicates`. The test clone has no such file, which is how it went unseen.
  `read_audio_header` is the fifth reader and not about names: an
  `AudioHeader` of what the file *claims* about its audio — bitrate and
  CBR/VBR mode, sample rate, bit depth (lossless only), length, encoder,
  ReplayGain — for `quality` to set beside a measurement. Its bitrate is
  mutagen's reading of the header, which for a VBR mp3 without a Xing/LAME
  header is the *first frame's*; that is the claim, and why `quality` measures
  the stream rather than trusting it. The encoder prefers LAME's own header
  (a tagger cannot touch it) over `TSSE`, which says "Lavf…" whenever ffmpeg
  re-encoded a rip. ReplayGain comes from the tag in any of five spellings
  (ID3's TXXX description is case-sensitive to mutagen, taggers disagree),
  else from the gain LAME stores in its header — 3 of 600 sampled files carry
  the tag, 139 the LAME gain.
- `rekordbox_db.py` — opening a `master.db` (explicit, or the local install's)
  and walking its content rows: what `rekordbox` and `quality` share, moved
  out of `rekordbox/reader.py` under rule 1 (its `sdm rekordbox` exports were
  byte-identical before and after). `load_files` converts rows to a plain
  `RekordboxFile` — Rekordbox's own claims about a file: bitrate, sample rate,
  bit depth, file type, length in whole seconds — where 0 means "not recorded"
  and is read as None. Those claims are not always right: 54 rows of the
  reference library list a ~130 kbps VBR mp3 as 32 kbps. Rows with no
  `FolderPath` are streaming entries and skipped. Read-only.
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
- `playlist.py` — the `Playlist`/`PlaylistTrack` model, playlist-link parsing,
  and the playlist CSV format **in both directions**: `read_playlist_csv`
  (lenient — columns found by alias, only title and artist required, because
  exporters disagree on header names and publish no spec) and
  `write_playlist_csv` (fixed — Exportify's column names plus `Playlist Name`).
  **They share a file so they cannot drift:** an export must read back into
  `playlist-diff`, and every column the reader uses is spelled as one of its
  aliases. Track references are held as Spotify URIs and turned into links on
  demand (`url`), so a URI, bare ID or open.spotify.com link in a CSV all land
  the same way. Export-only fields (release date, added at, …) stay at their
  defaults on a CSV read back; nothing that reads needs them. Stdlib only.
- `spotify.py` — PKCE login on a one-shot loopback server, then
  `GET /playlists/{id}/items`. Shared by `playlist-diff` and `playlist-export`.
  **Spotify's February 2026 changes are the constraint everything here is
  shaped around:** playlist contents only for playlists the user owns or
  collaborates on, app owner must have Premium, 5 users per app, `/tracks`
  renamed `/items` and `track` renamed `item` in each entry (both keys are
  read). A 403 raises `PlaylistNotAccessible`, a `SpotifyError` subclass, with
  a neutral message — **the advice is the caller's**, because it differs:
  `playlist-diff` says "export it to CSV with Exportify", `playlist-export`
  cannot say that about itself (same API, same 403) and says "copy it into a
  playlist of your own". Client credentials would be simpler and **cannot
  work**: no user, so nothing is owned. No client secret exists anywhere —
  PKCE needs only the ID (`SDM_SPOTIFY_CLIENT_ID`). Redirect URI defaults to
  `http://127.0.0.1:8765/callback` (`SDM_SPOTIFY_REDIRECT_URI` overrides;
  without a port, a free one is picked). Spotify rejects `localhost` by name.
  **The token is deliberately not saved** — that needs the persistent per-user
  location still unsettled for `dig` below; settle it there, then reuse it here.
  (The browser build's page keeps its own login in localStorage; that is the
  page's, not this module's.)
  **Two hooks exist for the browser build and nothing else**: `supplied_token`
  (set, `login` returns it instead of logging in) and `transport` (how
  `_request` sends; `urlopen` by default, failing as `urlopen` does). A tab has
  no socket for the loopback redirect or for urllib, so `sdm.browser` sets both
  and everything between — `fetch_playlist`, the 403/404 handling, the messages
  — stays this module's. Do not branch on "am I in a browser" here instead.
  Stdlib only; like `fpcalc_fetch.py`, a core module that touches the network.
- `report.py` — all CSV/JSON/sidecar writers. `newline=""` here is what stops
  the `csv` module writing blank lines between rows on Windows. `write_csv`
  takes `encoding="utf-8-sig"` for a file meant to be opened in Excel, which
  reads BOM-less UTF-8 as ANSI and mangles every accented name; only the
  playlist export uses it — the reports keep plain UTF-8, unchanged.
  Every report is opened with `REPORT_ERRORS` (`backslashreplace`), through
  `open_report` — which `analyze` streams its CSVs through too — so a lone
  surrogate in a file name lands as the text `\ud800` instead of crashing the
  writer. The catalog sidecar alone is `surrogatepass`; see "Text encoding".
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

**`--missing-metadata` is a second mode, not a fourth step.** It skips the
export entirely and runs `missing_metadata.run`: list every audio file whose
tags lack a title, an artist, or both, print them, and write
`out/catalog/missing_metadata_<folder>.csv` (`--output-csv` overrides the name,
same rules). A flag rather than a nested subcommand because `sdm catalog <dir>`
has a positional that argparse would try to read as the subcommand name.

It deliberately differs from the export in three ways. It covers all of
`AUDIO_EXTS` via `iter_audio_files` (so it also skips AppleDouble stubs, which
the export's own walk does not), because untagged files are disproportionately
WAV/AIFF. It reads through `core.tags.read_title_artist_raw`, not eyed3, so an
absent field is None rather than "Unknown". And a whitespace-only tag counts as
missing. An unreadable file is reported as missing both, with the reason in the
`error` column. The CSV is written even when empty, so a rerun after retagging
replaces the old list. Exit code 0, or 2 for a path that is not a directory.

**Measured baseline** (test clone, 3,664 files): ~8s, **36 missing** — 3 title
only, 16 artist only, 17 both (8 mp3, 8 wav, 1 aiff), 0 unreadable. The mp3s
missing both carry an ID3 block (encoder frames, Rekordbox's `TKEY`) with no
`TIT2`/`TPE1`. Exactly the set `read_title_artist` answers "Unknown" for, minus
the one literal "Unknown" artist.

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
9m12s wall, 64,157 candidate pairs, 178 confirmed, **158 groups** (148 pairs, 10
triples), 9 tracks unfingerprintable. (64,157 re-measured 2026-10-20 on both
sides of the multi-value tag fix; an earlier figure of 64,272 predates the
current tag readers.) Fingerprinting runs ~0.14s/track and is
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
  filename via `_scope_to_usb`), then raw ID3 tags. Opening the database and
  walking its rows is `core/rekordbox_db.py`'s, shared with `quality`; what a
  row becomes (a `Track`) stays here.
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

What each file's audio **is**, beside what its metadata **claims** — the
premise `analyze` rests on (the grid is a measurement, the tag is a claim),
applied to bitrate, bandwidth, loudness and the rest. `__init__.py` (parser) →
`command.py`: walk (`iter_audio_files`, every `AUDIO_EXTS` type, recursive, so
a USB root works) → per file, on a worker thread: names
(`core.tags.read_title_artist`), the file's claims (`core.tags.read_audio_header`),
Rekordbox's claims (`claims.RekordboxIndex` over `core.rekordbox_db.load_files`)
and the measurement (`measure.py`) → `compare.py` turns disagreements into
flags → one CSV, `out/quality/quality_<folder>.csv`. **Read-only.** The old
`analyzer.py` is gone: its "bitrate" was decoded PCM bytes over duration —
`sample_rate * 32` for every file — and pandas went with it.

- `measure.py` — **one decode per file, and that is the design.** ffprobe for
  the stream layout, then a single ffmpeg whose `ebur128` filter (with
  `peak=true`) measures loudness and true peak *on the way through*, while the
  PCM it outputs streams into numpy for clipping, the spectrum, effective bit
  depth and stereo correlation. **`-v verbose` is load-bearing**: only at that
  level does ffmpeg end with the input stream's packet bytes (bytes over decoded
  duration is the true bitrate — tags and cover art are not packets) and its
  decode-error count. Its stderr runs to several KB before any audio, more than
  a Windows pipe buffers, so it is drained on a thread. The spectral cutoff is
  the highest frequency above -60 dB relative to the 1–8 kHz median, and
  *sharp* when the level falls ≥25 dB across it; the smoothing pads with edge
  values, because zero padding lifted every lossy file's floor at Nyquist above
  the threshold and made the whole library look full-band. Effective bit depth
  is exact (an int ≤24 bits survives float32), so 16-bit audio padded to 24
  shows. A file that decodes to nothing keeps only its error — ebur128 still
  prints a 0.0 dB "peak" over no audio. The reference USB's one such file is an
  AIFF whose FORM header claims 1,118 bytes of a 48 MB file.
  **`Decoders` is load-bearing for cancel.** Ctrl-C (and `sdm web`'s cancel,
  the same signal) reaches the ffmpegs running at that moment, but worker
  threads start fresh ones from queued files in the half-second before the
  main thread notices, and each of those decoded a whole track: a cancel took
  9.7 s. Every ffprobe/ffmpeg is registered; an aborted run kills what is in
  flight and starts nothing more — 0.8 s, no process left. Killing is fine
  here, unlike for the Python process, because these only read.
- `claims.py` — `RekordboxIndex`: a file's row by path, then by
  (name, size) — how a USB copy is recognized, 3,064 of 3,069 on the reference
  USB — then by name only if exactly one row has it. A shared name matches
  nothing rather than putting another file's claims beside this measurement.
  The report's `rb_match` says which.
- `compare.py` — `Flag(kind, text)`. **Every threshold is named there and was
  set against the full reference library, not picked** — read the comments
  before moving one. A "?" in a kind (`transcode?`, `lossy source?`,
  `upsampled?`) is evidence, not a verdict, as `maybe` is in `playlist-diff`.
  Bitrate is compared only for lossy audio; a lossless file's is just its
  compression ratio.
- `command.py` — threads, not processes: the work is ffmpeg plus numpy that
  releases the GIL, and processes measured only 8% faster. The main thread
  waits with a 0.5 s timeout so KeyboardInterrupt lands. Results are sorted by
  path, so a report is byte-identical whatever `--jobs` was (checked at 2 and
  4). Columns are grouped by aspect: measured (no prefix), then
  `meta_` (the file's header and tags), then `rb_`; `issues` holds the flag
  kinds and `flags` the sentences, same order — the web view filters on the
  former.

The Rekordbox claims come from the **local** `master.db` (or `--db-path`), read
through pyrekordbox; without it, or with `--no-rekordbox`, the `rb_` columns are
blank and the run says why. A USB's own `export.pdb` is not read — pyrekordbox
0.4.4 cannot parse DeviceSQL — so a USB without the local library behind it
gets the file's own claims only. That reader is the next piece of this feature.

**Measured baseline** (`test-sdm-lib-clone/pioneer-usb-full-clone`, 3,664 files,
default `--jobs` 8): 52m20s warm, 63m cold; 3,663 measured, 1 undecodable (the
AIFF above). Rekordbox matched 3,069 (name+size 3,064, name 5). **484 flagged**:
clipping 227, transcode? 196 (123 at 320 kbps, 70 at 192 — most with no encoder
tag, converter-site style), rekordbox bitrate 66 (VBR without a Xing header:
Rekordbox reads the first frame, so 48 show 32 kbps and 12 show 320), mono in
stereo 23, header length 1 (a file claiming 8:04 that holds 7:00), and
undecodable 1. Loudness median -9.9 LUFS (p1 -18.4, p99 -6.2); true peak above 0 dBTP in
3,071; clip rate median 0.0009%, p90 0.054%. Cutoffs: honest 128s at
16.1–16.9 kHz, honest 192s at 18.8–19.1, honest 320s at 19.5 and up, most at
20–20.5. Use these as the regression check: different counts on this folder
mean the detector or a threshold changed. Two runs were cell-for-cell
identical in every measured and claimed column.

**Why a run is slow on this machine, and what it is not.** ~2 s of ffmpeg per
track, true peak a third of it (ebur128's 4x oversampling; dropping it saves
~30% of wall time). But 8 jobs on 8 cores gave only 1.3–2.5x over serial, and
not because of the GIL: plain `ffmpeg → NUL` scaled the same. The antivirus
(`fmservice64`) used ~2.5 cores scanning every file ffmpeg opened while total
CPU sat at 38%. More `--jobs` will not help past ~4 here; `--limit` samples.

`--output-csv` requires a value here, while `rekordbox --export-csv` accepts the
bare flag. That asymmetry is deliberate: this parser has a positional
`directory`, and an `nargs="?"` flag would swallow it — `sdm quality
--output-csv F:/Songs` would read the folder as the CSV name and then fail for
a missing directory. `rekordbox` has no positional, so it is safe there.

### `playlist-diff`

`__init__.py` (parser) → `command.py`: load the playlist (a CSV path via
`core.playlist.read_playlist_csv`, or a link via `core.spotify`) → read the
folder's tags (`core.tags.read_title_artist_raw`, all of `AUDIO_EXTS`) → match →
write `missing_<playlist>.csv` and `matched_<playlist>.csv` to
`out/playlist-diff/`. **Read-only** on the playlist and the files. The Spotify
client and the playlist model started out in this package and moved to core
when `playlist-export` needed them (rule 1); a 403 from Spotify is reported
here with the CSV advice, not as a failure.

- `matching.py` — title + artist, three outcomes: `owned`, `maybe`, `missing`.
  **`maybe` is the design, not a hedge:** a false `owned` hides a track the user
  will never buy, so a different version (original vs a named remix) or a file
  with no artist to confirm stays visible with the file it nearly matched.
  `NEUTRAL_VERSION_WORDS` is what makes "Extended Mix" and "Radio Edit" the
  same track; anything else in a version (a remixer, dub, vip) must agree.
  Artists split on `/` first among others, because that is how 304 tags on the
  test clone list several artists. Each file is read several ways (tags,
  "Artist - Title" inside the title tag, cleaned filename) because the
  library's worst-tagged files are rips that only have the name in one place.
  Deliberately **not** `core/text.py`'s normalizers: neither handles
  Spotify's `Title - Remix` convention or accents, and adding a third
  strictness there would muddy the documented two. **When `dig` needs "is this
  owned", this module moves to `core` (rule 1); it is not imported across.**

**Measured** on the test clone: a full run reads 3,664 files in ~9s. A synthetic
55-track Exportify-format playlist built from the library (owned tracks
re-spelled Spotify-style, rips matched via title tags, fake remixes, invented
tracks, real titles under wrong artists) came out 55/55 as constructed. That is
a consistency check, not an accuracy figure — no real Spotify playlist has been
run, since that needs the user's client ID.

### `playlist-export`

`__init__.py` (parser) → `command.py`: parse the link → login → fetch →
`core.playlist.write_playlist_csv` to `out/playlist-export/<playlist>.csv`
(`--output-csv` through `resolve_output`, same rules as everywhere). The whole
feature is messages and a default path; everything that knows Spotify or the
CSV format is in core, shared with `playlist-diff`. **Read-only** against
Spotify — read-only scopes, one file written.

**Its other job is to stand in for the missing saved login.** Every run logs
in, so the workflow for repeated diffs is export once, then
`playlist-diff <the csv> <folder>` as often as needed. That only works because
the writer and reader share `core/playlist.py`; a change to either must keep
the round trip (export → read back → same titles, artists, durations, URIs,
playlist name).

It **cannot** export someone else's playlist — same endpoint, same 403 — so it
must not suggest itself as the way around `playlist-diff`'s 403. Its own advice
is to copy the tracks into an owned playlist.

Podcast episodes and tracks Spotify removed (null `item`) are skipped and
counted, not written. Local files are written, with their `spotify:local:` URI.

**Verified** against a simulated API only (`_get` and `login` patched, the real
`fetch_playlist` paginating two pages): every column, quotes and accents, the
BOM, local files, skipped counts, `--output-csv` both forms, the 403 message,
and the round trip into `playlist-diff` against the test clone. No real Spotify
call has been made with a real client ID.

## `sdm web` — the front end

`__init__.py` (parser, argparse only) → `server.py` (stdlib `ThreadingHTTPServer`:
the built page plus a JSON API) → `schema.py`, `jobs.py`, `reports.py`. The page
is `frontend/`, built into `static/`. Stdlib only on the Python side, so `sdm web`
needs no extra; Node is a build-time dependency of the page, never of the server.

- `schema.py` — **the forms are the argparse tree.** `cli.build_parser()` is
  read through `_actions`/`_choices_actions` (underscored, but what argparse's
  own help formatter uses), so a new flag on any command appears in the UI with
  no web change. Form values go back to an argv here and are **parsed by a fresh
  real parser before anything runs**, with `error` patched to raise rather than
  `sys.exit` — not `redirect_stderr`, which is process-global and this runs on
  a server thread. `PATH_HINTS` (keyed by `dest`, consistent across features)
  is the only thing argparse cannot say: which boxes get a Browse button. A
  checkbox always means "pass this flag", so `--no-key-match` (store_false,
  dest `key_must_match`) is ticked to pass it. Positionals go after `--`.
- `jobs.py` — **one subprocess per run**, `python -m sdm.web.child`. Three
  reasons, any one sufficient: commands report by `print`; `core.paths` roots
  are process-global; a process can be stopped and a thread cannot. **Cancel
  must not kill**: the child is in its own process group
  (`CREATE_NEW_PROCESS_GROUP`), gets `CTRL_BREAK_EVENT`, and `child.py` maps
  SIGBREAK to KeyboardInterrupt — so `finally` blocks run and a borrowed fpcalc
  is deleted. Only a child alive after `CANCEL_GRACE` (15s, longer than
  `_purge`'s retries) is killed. The flip side of the own-group: a child does
  not see the Ctrl-C that stops the server, so `shutdown()` cancels every
  running job, and `serve` calls it in a `finally`. `PYTHONIOENCODING=utf-8`
  on the child, or a piped stdout on Windows uses the ANSI code page and dies on
  the first track name outside it. Outputs are the `wrote <path>` lines every
  command prints, plus anything under `out/<command>/` touched during the run
  (catalog's exporter prints dicts, not "wrote"). One run per command at a
  time — a second would overwrite the first's report. Jobs are in memory.
- `reports.py` — generic on purpose: CSV as rows, anything else as bytes. The
  dedicated views interpret report formats **in the browser** from each
  feature's file names and columns; nothing here imports a feature. CSVs under
  64 MB are parsed once and cached (filter, numeric-aware sort, blanks last in
  either direction); larger ones (`--export-beats`) are paged by streaming only.
- `server.py` — **who else can call the API is the design question**: it starts
  commands and reads files, and any website in the same browser can send
  requests to 127.0.0.1. Four layers: bound to 127.0.0.1; a per-launch token
  exchanged at `/auth` for an HttpOnly SameSite=Strict cookie (named per port —
  cookies ignore ports); a `Host` check against DNS rebinding; and refusal of
  `Sec-Fetch-Site` other than same-origin/none plus a foreign `Origin` on
  POST, because SameSite treats every port on 127.0.0.1 as one site. Do not
  add CORS headers or an `0.0.0.0` bind without redesigning this; LAN access
  was considered and declined. Served narrowly: reports only under the out root
  or a path a job reported writing, audio only in `AUDIO_EXTS` (with Range, for
  seeking), directory *names* for the path picker. Two Windows traps fixed
  here: `mimetypes` reads the registry, where `.js` is often `text/plain` and
  breaks module scripts, so static types are hardcoded; and `SO_REUSEADDR`
  lets a second socket share a taken port on Windows, so it is off there and
  `SO_EXCLUSIVEADDRUSE` is on. Default port 8770, never 8765 (Spotify's login).
- `frontend/` — hash routing (one page, no server routes), one `<audio>` for
  the whole page (`player.tsx`), types mirroring the API in `api.ts`. Views:
  `DuplicatesView` (any `duplicates.json`; A/B keeps the playback position
  within a group; warns on metadata-only groups), `PlaylistDiffView` (only for
  files in a `playlist-diff` folder — catalog's `missing_metadata_*.csv` has the
  same shape of name — and it checks the columns, falling back to a table),
  `QualityView` (any `quality_*.csv`, columns checked the same way: each
  aspect's measured value with its `meta_`/`rb_` claims beneath, a contradicted
  claim highlighted by `compare.py`'s tolerances — the flags themselves always
  come from the report, never recomputed in the page — issue chips from the
  `issues` column, and a measured / file / Rekordbox table per track),
  `TableView` for everything else. `pages/SpotifySetup.tsx` (`#/spotify`,
  *Spotify setup* in the sidebar) is the step-by-step client ID guide for both
  builds, linked from `--client-id`'s field; the redirect URI it shows comes
  from the session (`spotify_redirect_uri`: `SDM_SPOTIFY_REDIRECT_URI` or
  core's default), and `?section=` scrolls to a heading, since the router owns
  the `#`. Its facts are Spotify's and move; it says when they were checked. A play button appears only on a path that is
  absolute on this machine, because analyze's `device_path` (`/Contents/…mp3`)
  is a USB path the server cannot open. `npm run dev` proxies `/api` and `/auth`
  to a running `sdm web` and rewrites `Origin`, or the POST check refuses it.

**Read-only like what it runs.** No view deletes or moves a file, and none
should: the commands' read-only contracts are the point.

**Verified** with no browser tool in the loop: an HTTP test script against a
live server (auth, every refusal above, paging/filter/sort, Range audio, path
traversal, a real `catalog --missing-metadata` job and its outputs), a cancel of
a real `duplicates` run mid-fingerprint with a borrowed fpcalc (cancelled in
0.3s, `tmp/` empty after), `shutdown()` with a job running, the Vite proxy, and
headless Edge via `puppeteer-core` for every view in light, dark and phone
width (A/B position carry-over measured, zero console errors). Not yet done: a
Spotify login driven from the UI with a real client ID. `QualityView` the same
way: a `quality` run started from the form, its output opened from the job
page, chips, sort, details, highlighted claims, the Table tab, light/dark/phone
with no page overflow; the full 3,664-row report loads in 170 ms. A `quality`
job cancelled from the page ended in 0.8 s with its whole process tree gone and
the previous report untouched.

## The browser build — sdm.eigenomar.com

The third front end. Static files on Cloudflare Workers (`wrangler.jsonc`:
assets only, no Worker script); Python runs in the visitor's tab through
Pyodide 314.0.7 (Python 3.14) in a Web Worker. Online: `catalog` (both modes),
`analyze`, `playlist-diff` (CSV or link), `playlist-export`. Not:
`duplicates`/`rekordbox` (fpcalc), `quality` (ffmpeg). **`cli.py` and every
feature are unchanged** — `sdm.browser.ONLINE_COMMANDS` and `HIDDEN_FIELDS`
cut the forms down instead, and the Spotify login goes through
`core.spotify`'s two hooks.

- `frontend/src/api.ts` stays the page's only link to a backend.
  `vite build --mode browser` redirects every import of it to
  `src/browser/api.ts` (a plugin in `vite.config.ts`; `src/browser/` itself
  still gets the real one, for `ApiError`), which answers the same calls in the
  tab. Shared components ask `browser` — `null` in the server build — for the
  little only the browser has: the boot screen, a picker instead of
  `PathPicker`, `isPlayable`/`audioSrc` for the player. **Keep browser-only
  behaviour behind `browser`**, so `npm run build` and `sdm web` stay as they are.
- `src/sdm/browser.py` — one entry point, `call(name, args_json)`, answering
  JSON with the status `sdm web`'s server would have sent. `boot`, `commands`,
  `prepare` (form -> argv through `schema.build`; refuses an offline command, a
  path not picked in this tab, a Spotify link), `run` (`cli.main` in process),
  `outputs` (the `jobs.py` rule), `table` (`reports.TableReader`).
- `src/browser/worker.ts` — boots Pyodide, mounts picks, runs one command at a
  time; messages are handled strictly in order. `src/browser/api.ts` — job
  records and logs (polled exactly as from the server), a copy of every report,
  the picked folders.

What is load-bearing:

- **Module worker.** Pyodide 314 refuses a classic one ("Classic web workers
  are not supported"), hence Vite's `worker.format: "es"`.
- **The pyrekordbox shim** (`browser._shim_pyrekordbox`). `import
  pyrekordbox.anlz` runs the package `__init__`, which imports the database
  layer — sqlcipher3, with no Pyodide build. A bare module carrying the
  package's `__path__` goes into `sys.modules` first; `anlz` itself needs only
  construct and numpy. Wheels are `--no-deps` for that reason (and eyed3's
  spurious `coverage`). numpy and packaging (eyed3's `deprecation` imports it)
  are Pyodide's own builds. No micropip: `loadPackage` installs wheel URLs.
- **The mount filter** (`src/browser/files.ts`). Only audio (`AUDIO_EXTS`,
  AppleDouble stubs included — the catalog export counts them) and anything
  under `USBANLZ` is mounted: 14,851 of 29,593 files on the reference USB, the
  rest being `PIONEER/Artwork`. The rules come from `browser.boot`, i.e. from
  `core.track` and `core.anlz`, so they cannot drift. Handing the Files to the
  worker fell from 6.6–10.5s to 2.3–3.0s.
- **NTFS order in `readdir`.** The catalog export writes rows in `os.walk`
  order, so matching a Windows run byte for byte needs NTFS's listing order
  (each UTF-16 unit uppercased, compared unit by unit). Sorting files before
  mounting cannot give it: WORKERFS keeps a directory in a plain object, and
  objects list integer-like keys ("1977") first. `worker.ts` replaces WORKERFS's
  `readdir` with a sorted one.
- **The block cache in WORKERFS's `read`.** Every read is a blob slice plus a
  synchronous FileReaderSync round trip, ~0.7–1 ms almost regardless of size,
  and tag readers make several small reads per file. Reads go through 64 KiB
  blocks, 4 kept per open file — the file's own bytes, so it cannot change a
  result. `--missing-metadata`: no cache 33–35s, 64 KiB 18–20s, 256 KiB 18s,
  1 MiB 28s (it reads 5.9 GB). `?block=N` on the page (0 = off) overrides it
  and logs each run's I/O to `console.debug` — a measuring knob.
- **Cancel interrupts Python, and a cancelled run changes no report.**
  `_headers` sends `Cross-Origin-Opener-Policy: same-origin` and
  `-Embedder-Policy: require-corp` (Vite's browser-mode dev server too), so the
  page is cross-origin isolated and has SharedArrayBuffer. The page writes the
  job's number, then SIGINT, into an Int32Array shared with the worker
  (`protocol.ts`), and Pyodide's interrupt buffer turns that into a
  KeyboardInterrupt, `finally` blocks and all. Three things make it safe:
  - *All or nothing for `/out`.* `worker.ts`'s `run` renames `/out` aside and
    runs into an empty one; `putBack` then restores the earlier reports, and
    keeps what the run wrote only if it was not cancelled. Renames, no copies.
    It relies on no command reading its own earlier reports (none does).
    Whether a run was cancelled is the shared job number, read after the run,
    not how Python ended: a cancel landing as a command finishes still cancels.
  - *`browser._on_cancel`* raises only inside `run`'s `try`, and once per run.
    A late cancel reaches Python during some other call, which must not fail
    for it; the page signals every 250 ms, because Pyodide clears the buffer
    unatomically and can drop a write; a second raise would cut the first
    one's `finally` short. The worker clears a stale signal before each run.
  - *The old cancel as the fallback:* without isolation, or if the command has
    not stopped after 5s (`CANCEL_GRACE_MS`), the page terminates the worker
    and starts another, which re-mounts every pick and restores every report.
  Measured on the reference USB: `catalog` cancelled 0.2s after the click,
  `analyze` 0.4s (both including the page's poll); an `analyze` rerun cancelled
  20s into rewriting its reports left the page's copies the same objects and
  Python's own tables at 3,665 / 76,118 rows, and the next run was
  byte-identical. Isolation costs nothing measurable: `analyze` 84.6s/84.7s
  isolated, 91.7s/84.0s not, back to back. The restart fallback: 0.2s.
- **Reports live on the page as well as in Python's `/out`.** After each run
  the worker sends every file the run wrote back as bytes. Those copies
  are what survives a restart, what `api.reports()` lists (instantly, even while
  a run blocks the worker) and what *Open raw* opens; `api.table()` goes to
  Python and waits out a run. Each report is held twice, which matters only for
  `--export-beats`.
- **Pickers.** Chromium: `showDirectoryPicker` — asks to *view*, and the handle
  crosses to the worker uncloned and is walked there. Firefox/Safari:
  `<input webkitdirectory>` — browsers word it as an upload — filtered on the
  page and handed over 1,000 Files per message so progress can show; Chromium
  offers it too ("use the other picker") for a folder it refuses. Mounted at
  `/music/<folder name>`; a pick of a same-named folder replaces the mount.
  Picks die with the tab but form values persist, so `prepare` checks the path
  and says to pick again.
- **The CSP** (`src/browser/_headers`): `default-src 'none'`, and
  `connect-src 'self' https://accounts.spotify.com https://api.spotify.com` is
  what makes "your files never leave the browser" enforced rather than
  claimed, in the page and the worker alike. The two Spotify hosts are the
  playlist commands' and nothing else. `'wasm-unsafe-eval'` for Pyodide,
  `media-src blob:` for playback. Everything is self-hosted for this reason —
  do not add a CDN or any other origin. A test that byte-compares reports
  needs a second tab with CSP bypassed: `fetch(blob:)` is connect-src.
- **The Spotify login** (`src/browser/spotify.ts`). The tab itself goes to
  Spotify's login and comes back to the site root with a code (PKCE, the
  visitor's own client ID, scopes from `core.spotify.SCOPES` via boot),
  traded for a token as the module loads; the query comes off at once so a
  reload cannot resend it, and the hash route the login started from is
  restored. A redirect rather than a popup because the page's COOP cuts a
  popup's `opener`; the cost is a reload, which forgets picked folders and
  reports — so the box says to log in first, and says what it would forget.
  That cost is also why the login is **kept in localStorage** (unlike the
  CLI's): once per browser, renewed with the refresh token 5 min before
  expiry, until *Log out*. The pending verifier is there too, read back before
  leaving. `/me` is called at login because a development-mode app lets anyone
  log in and then answers 403 to accounts not on its user list; without it
  that would surface at the first run. The client ID is each visitor's own
  (5 users per app), with a 32-hex soft check. Each run of a command with a
  `playlist` field is handed `{client_id, token}` (`browser/api.ts` → worker →
  `sdm.browser.run`), which `_spotify_login` installs for that run only, and
  `prepare` refuses a link without one — before the command would say to set
  an environment variable. The worker reads the API with synchronous
  XMLHttpRequest (`_xhr`, over `pyodide.http.pyxhr`) as `core.spotify.transport`.
- **Self-hosted assets** (`build_browser.py`): only the four core files from the
  npm package `frontend/package.json` pins (keep `PYODIDE_VERSION` in step),
  numpy and packaging from jsDelivr checked against the lock's sha256, and the
  lock itself trimmed into `python.json` — so `pyodide/v<version>/` holds only
  release files and is cached as immutable. 16.0 MB on a first visit. The build
  fails if Cloudflare's limits are exceeded (Oct 2026: 25 MiB per file, 20,000
  files per version on the free plan); it makes ~25 files, the largest 9.6 MB.

**Measured baseline** (reference USB, Edge 155 headless, `wrangler dev`,
warm disk cache; native from the same machine): start 2.4–2.9s; picking the
USB 12–13s, ~10s of it the browser listing 29,593 files;
`catalog --missing-metadata` 18–20s (native 5.6s), `catalog` 21s (8.3s),
`analyze` 85–88s (68s), `playlist-diff` CSV 21s (8.3s). Every report
byte-identical to native once `C:\…\` paths are mapped to `/music/<folder>/…`
(and `analysis.json`'s CRLF, which is Windows text mode, not the browser).

**Verified** in headless Edge via `puppeteer-core` with the CSP enforced: all
four commands through the real forms, byte-compared; playback of a picked file;
cancel mid-`catalog` and mid-`analyze`, interrupting and restarting, with the
reports hashed before and after; light, dark and phone width with no
horizontal scroll; zero console errors throughout. `npm run build` and
`sdm web` re-checked unchanged. `showDirectoryPicker` was exercised through an
origin-private-file-system handle on a 153-file subset (CDP cannot answer that
picker for a real folder) — reports identical to the input picker and to
native. **Not verified:** that picker on a real folder, a drive root (`D:\`)
in either picker, the prompts' exact wording, Firefox and Safari, a real
Cloudflare deploy, and three cancel paths no test could time: the grace
fallback (a command that ignores the interrupt), a cancel landing just as a
run ends, and one sent while the run still waits behind another call.

**Spotify, verified** in headless Edge with the CSP enforced against a fake
Spotify: a local HTTPS server with a self-signed certificate, which Edge
reaches through `--host-resolver-rules` and `--ignore-certificate-errors`.
**Not puppeteer's request interception** — it stalls the worker's own fetches,
so Python never boots. Checked: the authorize request (client, S256 challenge
matching the verifier, root redirect, CLI scopes), the return to the starting
route with the query gone, nothing resent on reload, a cancelled login, a
`/me` 403, export and diff with a link (pagination, the page's token on every
worker request, through real CORS preflights), the CLI's 403 message for someone
else's playlist, renewal (old refresh token kept when none comes back), a
revoked refresh token, log out, other origins still blocked, and the box and
guide in light, dark and phone width. **Not verified:** a real Spotify login
with a real client ID, from either web front end.

## Conventions

- Windows-first. Paths in examples use drive letters; PowerShell is the shell.
- `core/` and the feature `__init__`/`command` modules use
  `from __future__ import annotations`, type hints, and module docstrings that
  explain *why*. Match that there.
- Code moved from the old layout (`api.py`, `runner.py`, `paths.py`,
  `exporter.py`) is looser and untyped. Match the surrounding file rather than
  upgrading it in place.
- Progress is reported by passing a `progress`/`log` callable, not by printing
  from library code. Keep `print` in `command.py` / handlers. `sdm web` relies
  on this: it shows whatever a command prints, draws a progress bar from any
  `N/M` in it, and finds reports by `wrote <path>` — keep printing those.
- `frontend/` is strict TypeScript with no linter; `npm run build` type-checks
  first. Match its existing style (2-space, double quotes, function
  components, a comment saying *why* above anything non-obvious).
- `.gitignore` excludes `*.csv`, `*.txt`, `out/`, `tmp/`, `deprecated/`, and
  `sync*.json`. **No CSV or TXT file in this repo is tracked** — every catalog
  export, report and sidecar you see is a local artifact.

## Text encoding

Two crashes, both fixed 2026-10-22, both from strings an encoder refused. What
follows is why each fix has the shape it has.

### Printing: `cli.main` changes the error handler, not the encoding

On Windows a redirected stdout is a plain file in the ANSI code page (cp1252)
with strict errors; only a real console gets UTF-8. So any `print` of a
character outside cp1252 raised `UnicodeEncodeError` and the command exited 1:
`catalog` lost its duplicate list and audit, `catalog --missing-metadata` its
listing, and `playlist-diff` — which prints each track before writing any
report — everything. The test clone has 48 non-cp1252 audio paths.

The first thing `cli.main` does, before anything can print (`--help`
included), is `reconfigure(errors="backslashreplace")` on stdout and stderr
(skipped where the stream is None, as under pythonw). Everything that printed
before keeps its exact bytes; whatever cannot be encoded prints as `\uXXXX`
— so a redirected file holds `강…`, not `강…` — and lone surrogates, which
not even strict UTF-8 can encode, print the same way. A console is untouched:
it is UTF-8, and 강남스타일 still shows as itself.

**Do not switch redirected output to UTF-8 instead**, which looks like the
obvious fix: PowerShell 5.1's `>` does not pass a program's bytes through. It
decodes them with `[Console]::OutputEncoding` (IBM437 on this machine) and
re-encodes, so UTF-8 output turns every non-ASCII character into mojibake
(`é` → `├⌐`) in the default shell, while cp1252 output is right there for
everything cp1252 covers. The README's "Where output goes" gives the recipe for
real characters in a redirected file (`PYTHONUTF8=1` plus a UTF-8
`[Console]::OutputEncoding`).

`sdm web`: `child.py` still runs with `PYTHONIOENCODING=utf-8` from `jobs.py`
— keep it, it is what makes the pipe UTF-8 — and only its error handler
changed, so a job that prints a surrogate name no longer dies. The browser
build: `sdm.browser.run` calls `cli.main` on every run; Pyodide's stdout is a
`TextIOWrapper`, `reconfigure` works on it, and repeating it is harmless.

**A trap when verifying anything here:** Claude Code's shell sets
`PYTHONIOENCODING=utf-8:surrogateescape`, which hides the crash. Run
`Remove-Item env:PYTHONIOENCODING` first, or use a fresh PowerShell window.
And capture a UTF-8 program's output (node, or `PYTHONUTF8=1`) with Git Bash's
`>`, not PowerShell's, for the reason above.

### Reports: a lone surrogate is escaped, except in the catalog sidecar

NTFS stores names as unvalidated UTF-16, so a file name may hold half a
surrogate pair, and `os.listdir` returns it as `'\ud800'`. Every report was
opened as strict UTF-8, so every report writer crashed on such a file, even
with `PYTHONUTF8=1`. The test clone has no such name; the fixtures were made by
copying a track to one.

What such a name looks like (decided 2026-10-22):

- **Reports**: the six characters `\ud800` — `REPORT_ERRORS` in
  `core/report.py`, also what `cli.main` prints for it. In JSON this is no
  approximation: inside a string it is JSON's own escape for that code point,
  and `json.load` gives the exact path back, which opens. In CSV it keeps the
  file valid UTF-8 for Excel, `sdm web`, `find_repeated` and
  `read_playlist_csv`, at the cost of an ambiguity a report can live with: in a
  full Windows path, `a\ud800.mp3` is also what a file `ud800.mp3` in a folder
  `a` looks like.
- **The catalog sidecar**: exact, `surrogatepass` in `write_lines` and
  `read_lines`. The cross-validation set-diffs the sidecar against a fresh
  walk, and must compare identities, not renderings — the ambiguity above
  would let two files share one line. `validate_mp3_csv` is unchanged. The cost:
  a line holding such a name is not valid UTF-8, so an editor shows
  replacement characters there. **Do not move the sidecar onto
  `REPORT_ERRORS`** to make it uniform.

Seen while verifying, not fixed: **`fpcalc` cannot fingerprint such a file** —
both fixtures came back unfingerprintable while their copies under ordinary
names matched, so `duplicates`/`rekordbox` count it among the unfingerprintable
(a `--skip-fingerprint` run does group it). Most likely the name does not
survive fpcalc's own conversion of its argument; not investigated.

### Verified

Fixtures in a scratch folder — the clone's PSY pair, an untagged `Трек.mp3`, a
playlist CSV with Korean titles, two NTFS names with lone surrogates — and
every crash above reproduced on the old code first. Then:

- `catalog` (both modes, the surrogate folder included) and `playlist-diff`:
  exit 0 and every report written under PowerShell `>`, `| Out-String`, cmd
  `> NUL` and Git Bash `>`; `sdm --help` and `sdm catalog --help` redirected.
- A real console (a new window, its screen buffer read back): 강남스타일 as
  glyphs, no escape, stdout `utf-8`/`backslashreplace`.
- The full clone, redirected, against a pre-fix worktree: `catalog`'s CSV and
  sidecar, the `--missing-metadata` CSV, and `analyze`'s `analysis.csv`,
  `phrases.csv` and `analysis.json` byte-identical; the audit `is_valid: True`.
- Surrogate names: both `catalog` modes exit 0 with the audit `is_valid: True`;
  `duplicates --skip-fingerprint` JSON round-trips each path exactly.
- `sdm web`, a live server driven over its API: Korean titles in the job logs
  as themselves; a `--missing-metadata` job on the surrogate folder succeeds.
- The browser build's Python half in Pyodide under Node (the built wheels, the
  worker's batched stdout, `sdm.browser.boot` then `run`): the run log is
  identical before and after the fix.

Not verified: `quality` and `playlist-export` redirected with a non-cp1252
name to print (same mechanism, no fixture), a real browser tab, POSIX.

## Planned work

Four features are designed but **not implemented** — see the "Ideas" section at
the end of `README.md` for what each one is and why. Nothing named there exists
in the tree; do not read a mention of one as a module to import or extend.
(The fifth, a deeper `sdm quality`, is built; see its section above.)

1. **Library manager** — Rekordbox playlists, bulk tag/metadata edits, analysis
   import/export. New feature package; playlists first, because they are plain
   `master.db` rows and need no new format work.
2. **Serato / Traktor export** — one-way, onto a differently formatted USB.
3. **`sdm dig`** — finds records *not* in the library, from seeds (genre, style,
   artist, track, label, era, BPM/key) tuned by underground level and source,
   then filtered against what is already owned.
4. **Genre/style enrichment** — fills in what the local library's tracks
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
  pieces move to `core` first, they are never imported across features —
  `core/rekordbox_db.py` is where that move started, for `quality`.
- New dependencies stay extras, behind the handler, per rule 2 — Rekordbox
  writes via `pyrekordbox`. `sdm --help` must keep working with none of them
  installed.
- **`dig` breaks assumptions the local-only features share, so do not model it
  on them.** `playlist-diff`/`playlist-export` are the nearest precedent
  (network, a credential, a reproducibility gap: a playlist changes under
  them), but they make one kind of call to one service. `core/spotify.py` is
  already the Spotify adapter `dig` would start from.
  It is network-first, so its results are not reproducible from local inputs; it
  needs credentials (environment variables, never committed, and degrade to the
  sources that have keys rather than failing — `core/spotify.py` now does this
  for one Spotify client ID, see `SDM_SPOTIFY_CLIENT_ID`); and it needs a
  *persistent* cache, which neither `out/` (reports) nor `tmp/` (deleted on
  exit) is. The Spotify login token hit the same wall and stayed unsaved in
  the CLI and `sdm web` (the browser build has localStorage, so it saves its
  own), so this location now has two consumers. Spotify's February 2026
  changes also apply: search caps at 10 results per page, and track/artist
  `popularity` is gone for new apps — re-read the README source table before
  leaning on Spotify for scoring. Settle that third location before writing
  code. Each source is an adapter behind one interface, because most of the
  interesting ones are gated or closed — see the source table in `README.md`,
  and re-verify it, since the access rules move. It stays read-only against
  every service: it queries and reports, and never posts or follows.
