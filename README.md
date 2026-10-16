# sdm

A personal music-library toolchain for a DJ workflow, behind one command.

It covers a single pipeline — *catalog, reconcile, verify* — split into isolated
features that share a small common core:

```text
 sdm catalog     sdm duplicates  sdm rekordbox   sdm analyze     sdm quality
 catalog &       find dupes by   reconcile with  read Pioneer    verify real
 audit MP3s      how they sound  Rekordbox/USB   USB analysis    audio quality
      \               |               |               |               /
       \______________________ sdm.core ______________________________/
        track model · normalization · tags · fingerprints · ANLZ · reports

 sdm playlist-diff    —  which tracks of a Spotify playlist a folder is missing
 sdm playlist-export  —  a Spotify playlist to CSV
 sdm download         —  deprecated, not registered (see below)
```

Each feature is self-contained: it may use `sdm.core`, never a sibling. Heavy
dependencies are optional extras loaded only when their subcommand runs, so
`sdm catalog` works on a machine with no Rekordbox and no ffmpeg.

> **`sdm download` is deprecated and currently disabled.** It is not registered
> as a subcommand, so it does not appear in `sdm --help` and typing it reports
> that it is off. The code is untouched under `features/spotify/` — re-enable it
> by putting `spotify` back in `FEATURES` in [src/sdm/cli.py](src/sdm/cli.py).

## Feature status

Everything the tool is made of, in one table. Full usage for each command is
further down; this is the map.

**done** — works. **partial** — works within the stated limit. **stub** —
present in the parser or the code but does nothing. **planned** — not written,
see [Ideas](#ideas--not-implemented). **n/a** — not reachable from that
command's data source at all. **deprecated** — the code is in the tree but the
command is not registered, so nothing under it can be run today. A row marked
*(the command)* describes the feature as a whole; the rows under it are its
parts.

| Feature | Sub-feature | What it does | Input | Status |
| --- | --- | --- | --- | --- |
| `download` | *(the command)* | Downloads Spotify links, tags them, embeds cover art. The only feature that **writes audio** | Spotify URLs (`--link`), destination (`--output`) | **deprecated** — disabled in `cli.py`; the sub-rows below describe code that is still present but unreachable |
| | Track and playlist links | Downloads the one track, or enumerates a playlist and downloads each | `/track/` or `/playlist/` URLs, mixable in one run | done |
| | Album and artist links | A whole album or artist catalogue in one command | — | planned — the link test matches the two above and rejects the rest |
| | Tagging and cover art | Writes ID3 frames and embeds the cover as `APIC` | The metadata the API returns with the audio | done |
| | Layout and naming | Folder per playlist; `Artist - Track` or reversed | `--folder`, `--tf` | done |
| | Skip what is already there | Drops tracks already in the destination before fetching | The destination's existing filenames | partial — `.mp3` names only |
| | Zero-byte cleanup | Deletes the empties a failed download leaves behind | The destination folder | done |
| | Logging | Appends to `out/logs/download.log` | `--disable-log` | done |
| | GUI | A Tkinter shell over the same run | Absence of `--disable-gui` | stub — the branch is `pass`, so `--disable-gui` is *required* |
| | `--dry-run` | Would preview a run without fetching | `--dry-run` / `-n` | stub — reaches `Cfg`, read nowhere. **The run downloads for real** |
| | `--pre-order`, `--sync`, `--run-pp` | Playlist order; folder-to-playlist sync; post-processing | The flags | stub — parsed, never acted on |
| | Exit code | Should report whether the run succeeded | — | partial — `run()` returns `None`, so always 0 |
| | SHA-256 duplicate remover | Deletes byte-identical copies in a tree | A directory | stub — never called, and prompts via `input()`. `duplicates` supersedes it |
| `catalog` | *(the command)* | An **auditable** MP3 catalog: an export, a duplicate report, and a proof the export is complete | A directory, `--output-csv`. **Use backslashes** | partial |
| | CSV export | Index, filename, track name and artist per file, tags via eyed3 | The directory, walked recursively | done |
| | Path sidecar | Every path the export visited, one per line, beside the CSV | The same walk | done |
| | Duplicate report | Groups rows normalizing to the same title and artist, mix suffixes stripped first | The CSV it just wrote | done |
| | Cross-validation | Re-walks the directory and set-diffs it against the sidecar | The directory and the sidecar | partial — a forward-slash argument reports **every** file as both missing and extra |
| | Unreadable tags | Reported per file rather than aborting the export | — | done |
| | Missing metadata | Lists every track whose tags lack a title, an artist, or both — every audio format, not just MP3 — telling an untagged file from an unreadable one | `--missing-metadata` | done |
| | Non-MP3 files | The rest of `AUDIO_EXTS` | — | planned — `.mp3` only |
| | Exit code reflects the audit | Should fail the command when `is_valid` is false | — | stub — always 0, so a failed audit cannot gate a script |
| `duplicates` | *(the command)* | Finds duplicates in a folder by what tracks **sound like** — catching renamed copies and mp3/flac pairs that name, size and hash checks miss. **Read-only** | A directory, searched recursively | done |
| | Walk and tag read | Collects audio files and reads BPM, key and duration across ID3, Vorbis and MP4 | The directory | done |
| | Duration prefilter | Buckets tracks of similar length — the one dimension always present, since it is decoded not tagged | `--duration-tolerance` | done |
| | BPM / key prefilter | Sharpens the bucketing, at the cost of dropping untagged files | `--require-bpm`, `--require-key`, `--bpm-tolerance` | done |
| | Fingerprint confirmation | Compares each candidate pair by chromaprint | `--fingerprint-threshold`, `--skip-fingerprint` | done |
| | Grouping | Union-find, so a track duplicated three ways is one group, not three pairs | The confirmed pairs | done |
| | Report | CSV and JSON, the same shape `rekordbox` writes so the two can be diffed | `--output-dir` | done |
| | `fpcalc` pre-flight | Fails in seconds on a broken binary instead of reporting "0 groups" hours later | — | done |
| | Borrowed `fpcalc` | Fetches a pinned Chromaprint into `tmp/` for the run, then deletes it — including on Ctrl-C | `--fpcalc-path`, `--no-fetch-fpcalc` | done |
| | Acting on the results | Moving or deleting what it finds | — | planned, deliberately — the report is the output |
| `rekordbox` | *(the command)* | Reads a Rekordbox library — track list plus **analyzed** BPM, key and duration — and exports it or reports duplicates. **Read-only** | `--usb-path` or `--db-path`; else the local install | partial |
| | Source resolution | USB `master.db`, then the local one scoped to the USB (the only source with analyzed BPM and key), then raw ID3 tags | `--usb-path`, `--db-path` | done |
| | Track export | Title, artist, BPM, duration and key to CSV | `--export-csv`, bare or with a path | done |
| | Duplicates by name | Title and artist alone, so it covers every track and needs no analysis | `--duplicates-by-name` | partial — blank artists on a local-DB-only run; attaching the USB fills them |
| | Duplicates by fingerprint | The detector `duplicates` uses, with BPM and key required | Tolerance and threshold flags | partial — needs `fpcalc` on PATH; no borrowing, no pre-flight |
| | Reading the exported database | `export.pdb` / `exportLibrary.db` off the USB | — | planned — encrypted DeviceSQL, skipped |
| | `analysis.py` | An older hand-rolled ANLZ parser | — | stub — unimported and wrong; superseded by `core/anlz.py`. Deletion candidate |
| | Playlists | Reading and managing them | — | planned |
| `analyze` | *(the command)* | Reads **Rekordbox's own analysis** off a Pioneer USB — what Rekordbox *worked out*, not what the library contains. Needs no install and no database. **Read-only** | A USB path, or a `PIONEER/USBANLZ` directory | done |
| | Beat grid | Every beat, plus grid BPM, first downbeat and whether the tempo varies | The `.DAT`/`.EXT` files beside each track | done — 3,655 of 3,665, incl. 119 files pyrekordbox rejects outright |
| | Phrase structure | Intro, verse, chorus, bridge and outro with start and end beats | The same files | done — 3,646 of 3,665 |
| | Phrase labelling | Resolves each phrase to one of 20 mood-dependent names; an unknown kind is reported, not guessed | The parsed phrases | done — all 76,118 resolved |
| | Title and artist | Read from the file's tags, since ANLZ stores a path and never a name | The tracks the USB paths resolve to | done — "Unknown" for the 38 untagged files |
| | Reports | `analysis.csv`, `phrases.csv`, `analysis.json`, `beats.csv` — written as tracks are read, so a full grid is never held in memory | `--output-dir`, `--limit`, `--export-beats` | done |
| | Cue points | Hot cues and memory cues | — | planned, low value — one hot cue in 3,665 tracks |
| | Waveforms | The rendered waveform data | — | planned, skipped on purpose — parsing them takes a scan from 49s to 8m28s |
| | Musical key | — | — | n/a — not in ANLZ at any version; use `rekordbox` |
| `quality` | *(the command)* | Measures what a file **actually is** and diffs it against what the tags **claim** | A directory (top level only), `--output-csv` | partial |
| | Sample rate, real vs claimed | `ffprobe`'s decoded rate against eyed3's | The file | done |
| | Bitrate, real vs claimed | Should expose a low-quality re-encode passed off as high | The file | stub — **the number is not a bitrate**, see below |
| | Report | A pandas DataFrame, printed or written to CSV | `--output-csv` | done |
| | Recursive scan | A library rather than one folder | — | planned — `os.listdir`, top level only |
| | Non-MP3 files | The rest of `AUDIO_EXTS` | — | planned — `.mp3` only |
| | Clipping, loudness, true peak | Peak levels, clipped-sample count, EBU R128 loudness and dynamic range | — | planned |
| | Transcode detection | The spectral cutoff that betrays a 128 kbps rip relabelled as 320 | — | planned |
| `playlist-diff` | *(the command)* | Lists the tracks of a Spotify playlist that a music folder does **not** have. **Read-only** on both sides | A playlist link or a CSV export of one, and a directory | done |
| | Spotify API | Reads a playlist after a browser login (PKCE; no secret, read-only scopes) | A link, URI or ID; `--client-id` / `SDM_SPOTIFY_CLIENT_ID` | partial — **only playlists you own or collaborate on**, a Spotify-imposed limit since February 2026; the app owner needs Premium |
| | CSV import | Any playlist, via an export from Exportify, TuneMyMusic and the like; columns found by name | A `.csv` path in place of the link | done |
| | Matching | Title and artist, version-aware: "Extended Mix" and "Radio Edit" are the same track, a named remix is not | The folder's tags, plus "Artist - Title" read out of title tags and filenames | done |
| | "Maybe" | A different version owned, or a file with no artist tag to confirm — listed with the file, never counted as owned | — | done |
| | Report | `missing_<playlist>.csv` (the answer) and `matched_<playlist>.csv` (which file each owned track matched) | `--output-dir` | done |
| | Saved login | Skipping the browser on later runs | — | planned — needs a persistent per-user location, not yet settled. Meanwhile, `playlist-export` once and diff the CSV |
| `playlist-export` | *(the command)* | Writes a Spotify playlist to CSV with Exportify's column names. **Read-only** against Spotify | A playlist link, URI or ID; `--output-csv` | partial — **only playlists you own or collaborate on**, the same API limit as `playlist-diff` |
| | Columns | URI, title, artists, album, album artists, release date, disc/track number, duration, explicit, ISRC, added by/at, playlist name | — | done |
| | Excel-safe | UTF-8 with a byte-order mark, so accented names open correctly | — | done |
| | Round trip | The file reads straight back into `playlist-diff`, playlist name included | — | done |
| *new* | Library manager | Rekordbox playlists, bulk tag and metadata edits, analysis import/export | A `master.db`, and a backup of it | planned |
| *new* | Deeper `quality` | The four `quality` rows above, together | A directory, as today | planned — extends `quality`, not a new command |
| *new* | Serato / Traktor export | One-way export of library and playlists onto a USB another ecosystem reads | The Rekordbox library, plus a destination USB | planned |
| *new* | `dig` | Finds records **not** in the library: seeds of genre, artist, track or label, tuned by underground level and source, cross-referenced against what is already owned | Seeds and tunables, plus API tokens; the first network-dependent feature | planned |
| *new* | Genre enrichment | Fills in genres and styles for tracks already owned, from Discogs, Last.fm and MusicBrainz | The local library, plus API tokens | planned — a prerequisite for `dig`'s scoring, not just a companion |

> **`sdm quality`'s bitrate column does not measure bitrate.** `analyzer.py`
> decodes the file to 16-bit stereo PCM and divides the byte count by the
> duration — which is `sample_rate x 32` for *every* file regardless of how it
> was encoded, so a 128 kbps rip and a true 320 both report ~1,411 kbps. It is
> then compared against eyed3's value in kbps, so the units differ by 1000 as
> well. The sample-rate half of the report is sound; the bitrate half needs the
> rewrite described under [Ideas](#ideas--not-implemented).

## Install

```ps1
pip install -e .              # base: catalog, duplicates, playlist-diff/-export
pip install -e ".[all]"       # everything
pip install -e ".[rekordbox]" # + Rekordbox reading and fingerprinting
pip install -e ".[analyze]"   # + beat grids and phrases off a Pioneer USB
pip install -e ".[quality]"   # + the bitrate checker
```

Requires Python 3.9+. Two features need external binaries on PATH:
`ffmpeg`/`ffprobe` for `sdm quality`, and `fpcalc`
([chromaprint](https://acoustid.org/chromaprint)) for fingerprint-based
duplicate detection.

`sdm duplicates` is the exception: if no `fpcalc` is installed it borrows one
for the run — downloaded into `tmp/`, used, and deleted again when the command
exits — so it works with nothing on PATH. `sdm rekordbox` still needs a real
installation for its fingerprint stage.

```ps1
sdm --help
sdm <command> --help
```

## Where output goes

Every generated report lands under one root, in a folder named for the feature
that produced it:

```text
./out/
  catalog/     mp3_file_list_<folder>.csv + _x_val.txt sidecar,
               missing_metadata_<folder>.csv with --missing-metadata
  duplicates/  duplicates.csv, duplicates.json
  rekordbox/   duplicates.csv, duplicates.json, tracks.csv
  analyze/     analysis.csv, phrases.csv, analysis.json (+ beats.csv on request)
  quality/     the bitrate report, when --output-csv is given
  playlist-diff/  missing_<playlist>.csv, matched_<playlist>.csv
  playlist-export/  <playlist>.csv
  logs/        download.log — only while sdm download was enabled
./tmp/         scratch, created and removed within a single run
```

Both roots are shared by every subcommand and resolve in this order — an
explicit flag, then the environment, then the default:

| | Flag | Environment | Default |
| --- | --- | --- | --- |
| Reports | `--out-dir DIR` | `SDM_OUT_DIR` | `./out` |
| Scratch | `--tmp-dir DIR` | `SDM_TMP_DIR` | `./tmp` |

```ps1
sdm catalog --out-dir D:/reports "C:\Users\omark\Music\postmodern"
```

Per-command output flags still override the default *name*, and how they are
read depends on their shape: a bare filename lands in the feature's directory,
while anything with a directory component is taken literally.

```ps1
sdm quality "F:/Songs" --output-csv report.csv        # -> ./out/quality/report.csv
sdm quality "F:/Songs" --output-csv D:/audit/q.csv    # -> D:/audit/q.csv
```

**Downloaded audio is not a report** and is deliberately left out of this. It
goes wherever `sdm download --output` points, untouched by `--out-dir` — while
that command is enabled.

---

## `sdm download` (deprecated, disabled)

> **This command is switched off.** `spotify` is not in `FEATURES` in
> [src/sdm/cli.py](src/sdm/cli.py), so it is absent from `sdm --help` and typing
> `sdm download` prints that it is disabled and exits 2. Nothing else in the
> toolchain depends on it, and no other command changed.
>
> The package stays in the tree untouched at `src/sdm/features/spotify/`. To
> bring it back, add `spotify` to the import and to `FEATURES`, and drop
> `"download"` from `DEPRECATED_COMMANDS`. Its base dependencies (`requests`,
> `tabulate`) are still declared, so nothing needs reinstalling.
>
> The rest of this section documents it as it stood, for whenever that happens.

Downloads tracks and playlists from Spotify, writes ID3 tags, and embeds album
art.

```ps1
sdm download --link "<spotify track or playlist url>" --output "F:/Songs" --disable-gui
```

`--disable-gui` is currently required — the GUI branch is a stub, so without it
the command exits without doing anything.

Multiple links can be passed at once, and tracks and playlists can be mixed:

```ps1
sdm download --link "<track url>" "<playlist url>" --output "F:/Songs" --disable-gui
```

By default each playlist gets its own folder; pass `--folder False` to download
everything flat. Tracks that already exist in the destination are skipped, and
zero-byte files left behind by a failed download are cleaned up.

| Flag | Default | Meaning |
| --- | --- | --- |
| `--link`, `-l` | — | One or more Spotify track/playlist URLs |
| `--output`, `-o` | `./downloads` | Destination directory |
| `--folder` | `True` | Create a folder per playlist |
| `--no-make-dirs` | off | Fail instead of creating missing directories |
| `--tf` | off | Name files `Track - Artist` instead of `Artist - Track` |
| `--disable-gui` | off | Run the CLI (required — see above) |
| `--quiet`, `-q` | off | Suppress console output |
| `--dry-run`, `-n` | off | **Not wired up — see below** |
| `--disable-log` | off | Suppress logging (otherwise `out/logs/download.log`) |

Four flags are accepted by the parser but never acted on: `--sync` and
`--run-pp` are read nowhere, and `--dry-run` and `--pre-order` reach the config
object but are never consulted.

> **`--dry-run` does not simulate anything — it downloads.** Nothing reads
> `cfg.dry_run`. Treat the flag as absent until it is implemented.

---

## `sdm catalog`

Walks a music folder and produces an **auditable** catalog — an export, a
duplicate report, and a proof that the export is complete.

```ps1
sdm catalog "C:\Users\omark\Music\postmodern"
```

Writes two files into `out/catalog/`:

- `mp3_file_list_<folder>.csv` — `#, filename, track name, artist` per track
- `mp3_file_list_<folder>_x_val.txt` — one raw file path per line

Then prints:

1. **Duplicates.** Titles are normalized (Unicode NFKC, casefolded, whitespace
   collapsed) and mix suffixes such as `(Original Mix)` or `- Original Mix` are
   stripped before grouping on `(title, artist)`. Extend `MIX_SUFFIXES` in
   `sdm/core/text.py` to cover `Extended Mix`, `Radio Edit`, and friends.
2. **Cross-validation.** The directory is walked a second time and set-diffed
   against the sidecar, reporting anything missing from the export, anything in
   the export no longer on disk, and any duplicate entries. A clean run reports
   `is_valid: True` — the guarantee this feature exists to provide.

Use `--output-csv PATH` to control the destination; the sidecar name is derived
from it, and the two always stay together.

> Pass the folder with **backslashes**. Cross-validation compares the sidecar's
> paths against normalized absolute paths, so a forward-slash argument makes
> every file look both missing and extra. A long-standing quirk, not a new one.

### Missing metadata

```ps1
sdm catalog "F:\Songs" --missing-metadata
```

Instead of the export, lists every track whose tags have no title, no artist,
or neither — the ones that will show up as blank or "Unknown" on a CDJ. Prints
one line per track and writes `out/catalog/missing_metadata_<folder>.csv`
(`#, missing, track name, artist, filepath, error`). `missing` is `title`,
`artist` or `title+artist`, and the field that *is* present is filled in, so a
track missing only its artist is still recognizable.

Unlike the export it covers every audio format, not just MP3 — untagged files
are disproportionately WAV and AIFF. A tag holding only spaces counts as
missing; a tag reading literally "Unknown" does not, since that is what the tag
says. A file that cannot be parsed is listed as missing both, with the reason
in `error`, so a corrupt file is not mistaken for an untagged one. Read-only:
it tells you what to tag and leaves the tagging to you.

The CSV is rewritten on every run, even when nothing is missing, so after
retagging, a rerun leaves no stale list behind. On the 3,664-file reference
library it takes ~8s and finds 36.

---

## `sdm duplicates`

Finds duplicate tracks in a **folder** by what they sound like. Not by filename,
size or checksum — so it catches the same recording saved twice under different
names, and an mp3 and a flac of the same track, which none of those would.

**Read-only.** It reports; it never moves, renames or deletes a file. Needs no
`fpcalc` installed (see [Install](#install)).

```ps1
sdm duplicates "F:/Songs"
```

### Which command to use

| Command | What it does | When to use it |
| --- | --- | --- |
| `sdm duplicates "F:/Songs"` | Groups tracks by duration, then confirms every candidate pair by audio fingerprint | The answer. Slow — budget ~0.14s per track |
| `sdm duplicates "F:/Songs" --skip-fingerprint` | Prefilter only, no fingerprinting | **Sizing, not answers.** Tells you how big the real run will be, in seconds |
| `sdm duplicates "F:/Songs" --require-key` | Adds musical key to the prefilter | Much faster, and nearly free if your files are key-tagged |
| `sdm duplicates "F:/Songs" --require-bpm` | Adds BPM to the prefilter | Only when you know the library is fully BPM-tagged |
| `sdm duplicates "F:/Songs" --output-dir "D:/reports"` | Writes the report elsewhere | Keeping a run's output outside the project |
| `sdm duplicates "F:/Songs" --fpcalc-path "C:\tools\fpcalc.exe"` | Uses your own fpcalc | You have one installed somewhere off PATH |
| `sdm duplicates "F:/Songs" --no-fetch-fpcalc` | Fails rather than downloading a temporary fpcalc | Offline, or you want the binary under your own control |

> **`--skip-fingerprint` output is not a list of duplicates.** Duration-only
> bucketing is deliberately permissive: on a 3,459-track folder it produced
> 57,176 candidate pairs, which union-find then chained into a single group of
> 3,297 tracks. Read it as a size estimate and nothing more.
>
> **`--require-bpm` can silently discard most of a library.** On the test
> library only 50% of files carry a BPM tag, against 99.8% for key — the flags
> look symmetrical but are not. Anything untagged is dropped before
> fingerprinting, and never appears in the report at all.

### How it decides

Two stages. A cheap **prefilter** buckets tracks that could plausibly match,
then a **chromaprint fingerprint** comparison confirms each candidate pair, and
confirmed pairs are linked into groups.

Duration is the only dimension always available — it is decoded from the audio
stream rather than read from a tag — so it is always required, and BPM and key
are opt-in via the two `--require` flags. A non-required dimension is still used
opportunistically whenever both tracks in a pair happen to carry it.

| Flag | Default | Meaning |
| --- | --- | --- |
| `--duration-tolerance` | `2.0` | Seconds two tracks may differ by and still be compared |
| `--bpm-tolerance` | `0.5` | BPM two tracks may differ by, when both carry one |
| `--require-bpm` | off | Prefilter on BPM; skips files with no BPM tag |
| `--require-key` | off | Prefilter on key; skips files with no key tag |
| `--fingerprint-threshold` | `0.85` | Similarity at which a pair is called a duplicate |
| `--skip-fingerprint` | off | Report prefilter candidates without fingerprinting |
| `--fpcalc-path` | — | Path to an fpcalc binary that is not on PATH |
| `--no-fetch-fpcalc` | off | Do not download a temporary fpcalc; fail instead |
| `--output-dir` | `out/duplicates/` | Where the report goes |

The threshold is `0.85` rather than something near zero because unrelated audio
scores about **0.5**, not 0 — half the bits of two random 32-bit words agree by
chance.

Before the real work starts, the command fingerprints a handful of files as a
pre-flight. Without it, a broken `fpcalc` would drop every pair and the run
would end hours later reporting "0 duplicate groups" — a clean bill of health
that means nothing.

### What a full run looks like

On the 3,664-file reference library:

```text
prefilter: 64272 candidate pair(s) from 3664 eligible track(s)
fingerprint: 9 of 3625 track(s) could not be fingerprinted
fingerprint: 178 pair(s) confirmed out of 64272
found 158 duplicate group(s)
```

Roughly nine minutes, almost all of it fingerprinting: 158 groups — 148 pairs
and 10 triples — from 64,272 candidates. Those numbers are the regression check;
a run on the same folder reporting far more or far fewer groups means something
changed.

---

## `sdm rekordbox`

Reads a Rekordbox library — canonical track list plus analyzed BPM, key and
duration — and reports duplicates. **Read-only by design:** it never writes to
the USB or to the Rekordbox database.

```ps1
# export every track's metadata (bare flag -> out/rekordbox/tracks.csv)
sdm rekordbox --usb-path D:/ --export-csv
sdm rekordbox --usb-path D:/ --export-csv library_with_analysis.csv

# duplicates by title + artist (covers every track, needs no analysis data)
sdm rekordbox --usb-path D:/ --duplicates-by-name

# duplicates by audio fingerprint (default), or --skip-fingerprint for a fast pass
sdm rekordbox --usb-path D:/
```

Reports go to `out/rekordbox/`; `--output-dir DIR` overrides that directory
alone, without moving the other features' output.

Data comes from, in order: a `master.db` you point at directly, then your
**local** Rekordbox `master.db` — the only source carrying analyzed BPM and key,
so it wins even when a USB is supplied, then scoped down to the tracks actually
on the USB — and finally raw ID3 tags as a last resort. The exported
`export.pdb` / `exportLibrary.db` on the USB are encrypted DeviceSQL and are
skipped.

Audio duplicate detection runs in two stages: a cheap prefilter grouping tracks
by BPM, key and duration within tolerance, then a chromaprint comparison to
confirm, with confirmed pairs linked into groups.

Full flag reference and setup notes: [docs/rekordbox.md](docs/rekordbox.md).

---

## `sdm analyze`

Reads **Rekordbox's own analysis** off a Pioneer USB — the beat grid it computed
and the phrase structure it detected for every track. Where `sdm rekordbox` asks
what the library *contains*, this asks what Rekordbox *worked out* about it.

**Read-only by design:** it opens the USB's analysis files and writes nowhere
near them.

```ps1
sdm analyze D:/                  # USB mounted at D:
sdm analyze D:/ --limit 50       # sample before committing to a full scan
sdm analyze D:/ --export-beats   # also dump every beat of every grid
```

The path may be the USB root or a `PIONEER/USBANLZ` directory directly.

This data lives only in `PIONEER/USBANLZ/` — not in the tags, not in the
exported database — so this is the one command that needs **no Rekordbox install
and no `master.db`**, which is exactly where `sdm rekordbox` is weakest.

Reports go to `out/analyze/`:

- `analysis.csv` — per track: title, artist, paths, grid BPM, whether the tempo
  varies, beat count, first downbeat, mood, phrase count, `intro_end_ms`,
  `outro_start_ms`, warnings
- `phrases.csv` — per phrase: label, kind, start/end beat, length in **bars**,
  start/end time
- `analysis.json` — the same nested per track
- `beats.csv` — only with `--export-beats`; millions of rows on a full library

| Flag | Default | Meaning |
| --- | --- | --- |
| `usb_path` | — | USB mount path, or a `USBANLZ` directory |
| `--output-dir` | `out/analyze/` | Where the reports go |
| `--limit N` | — | Stop after N tracks |
| `--export-beats` | off | Also write `beats.csv` |

### Phrase structure

Rekordbox analyses each track under one of three **moods**, and the mood decides
what a phrase is called. Mid and low name phrases by kind alone — Intro,
Verse 1–6, Bridge, Chorus, Outro. High uses fewer kinds and carries the variant
in separate flags, giving Intro 1/2, Up 1/2/3, Down, Chorus 1/2, Outro 1/2.

That is 20 labels, and on the reference USB all **76,118 phrases** resolved to
one of them — no unknowns. An unrecognized kind is reported as
`Unknown (mood M, kind K)` rather than given a plausible name, so a format change
shows up in the output rather than hiding.

Two things ANLZ does **not** carry: **musical key** (database only — use
`sdm rekordbox`) and, in practice, **cue points**. Cues are in the format but the
reference library of 3,665 tracks holds one hot cue and no memory cues, so they
are deliberately not parsed.

### What a full scan looks like

On the 3,665-track reference USB:

```text
read 3665 track(s)
  beat grid:       3655 (99.7%)
  phrase structure: 3646 (99.5%)
  mood: high 2314, mid 1251, low 81
  120 track(s) had at least one warning - see the report
```

About a minute — 49s warm, ~1m15s cold — against 8m28s for a naive parse,
because waveform tags are almost all of the bytes on disk and nothing here
renders them. The counts are the regression check; the wall time is I/O-bound
and will track your disk.

> **The grid BPM is a measurement; a `TBPM` tag is a claim.** On the 1,814 tracks
> carrying one, 17.3% disagree with the grid by more than 0.5 BPM — and 97 of
> those are tagged at exactly half the real tempo.

Beat-grid coverage is 3,655 where pyrekordbox alone manages 3,541: it declares
one `PQTZ` header word constant when only its high half is fixed, and parses each
file as a single struct, so that one field discarded 119 whole `.DAT` files.
Those grids are recovered, sanity-checked, and flagged in the report.

Format details, parser workarounds and the full baseline:
[docs/analyze.md](docs/analyze.md).

---

## `sdm quality`

Decodes each file with `ffprobe`/`ffmpeg` to measure its *actual* sample rate
and bitrate, then diffs those against what the ID3 tags claim — useful for
spotting re-encoded files passed off as high quality.

```ps1
sdm quality "F:/Songs" --output-csv quality_report.csv
```

---

## Spotify access

`sdm playlist-diff` (with a link) and `sdm playlist-export` read playlists
through Spotify's Web API, logged in as you. Both share this setup and these
limits.

### Which playlists work

**Only playlists you own or collaborate on.** That is Spotify's rule, not this
tool's: since the
[February 2026 Web API changes](https://developer.spotify.com/documentation/web-api/tutorials/february-2026-migration-guide),
the API returns playlist contents only to their owner or a collaborator, and
there is no app-level way around it. For anyone else's playlist — a friend's,
a label's, an editorial one — **copy its tracks into a playlist of your own** in
the Spotify app (select all, *Add to playlist*) and use that link, or export it
with a third-party tool such as [Exportify](https://exportify.net/) and give
`playlist-diff` the CSV.

### One-time setup

1. Open the [Spotify developer dashboard](https://developer.spotify.com/dashboard)
   and create an app. **The account needs Spotify Premium** — another of
   Spotify's 2026 requirements for apps in development mode.
2. Add the redirect URI **`http://127.0.0.1:8765/callback`**, character for
   character (`localhost` is rejected by Spotify), and tick *Web API*.
3. Copy the app's **Client ID** and make it available to sdm:

   ```ps1
   setx SDM_SPOTIFY_CLIENT_ID "<client id>"    # new terminals only
   ```

   or pass `--client-id` on each run. No client secret is needed or used.

Each run then opens the browser to log in. The first time, Spotify asks you to
approve the app; after that it is a redirect that closes itself. The login is
not saved between runs — which is what `playlist-export` is good for: export
once, then diff the CSV with no login. Pass `--no-browser` to get the URL
printed instead.

If port 8765 is taken, register a different loopback URI on the app and set
`SDM_SPOTIFY_REDIRECT_URI` to it. A URI registered without a port
(`http://127.0.0.1/callback`) lets sdm pick a free one each run.

The login asks only for read-only scopes (`playlist-read-private`,
`playlist-read-collaborative`), so the token could not change a playlist even
by mistake.

---

## `sdm playlist-diff`

Lists the tracks of a Spotify playlist that a music folder does **not** have —
the shopping list between what you have been listening to and what you can
actually play out.

```ps1
sdm playlist-diff "https://open.spotify.com/playlist/<id>" "F:\Songs"   # your own playlist
sdm playlist-diff "D:\exports\Digging Oct.csv" "F:\Songs"              # any playlist, as CSV
```

**Read-only on both sides.** It reads the playlist and the folder's tags and
writes only its two reports. The Spotify login asks for read-only scopes, so
the token could not change a playlist even by mistake.

### Link or CSV

A **link** goes through the Spotify API, so it needs the one-time setup in
[Spotify access](#spotify-access) and works only for playlists you own or
collaborate on.

A **CSV** needs no Spotify app and no login at all, and covers any playlist:

- one written by [`sdm playlist-export`](#sdm-playlist-export) — export once,
  then diff the file as often as you like without logging in again;
- one from [Exportify](https://exportify.net/),
  [TuneMyMusic](https://www.tunemymusic.com/) or similar, which is the way to
  compare **someone else's** playlist, since the API will not read it for you.

Columns are found by name — a title and an artist column are required, and
album, duration, ISRC and track link are used when present — so most exporters
work without configuration.

### How it matches

By title and artist. A shared ID would be better, but only 1.6% of the
reference library carries an ISRC. Both sides are normalized the same way:

- **Versions.** Spotify's `Title - Extended Mix` and a tag's
  `Title (Extended Mix)` are the same thing. Words that name a *release* —
  original, extended, radio edit, club mix, remastered 2011 — are ignored. What
  names a different *recording* — `Solomun Remix`, `Dub`, `VIP`,
  `Instrumental` — has to agree.
- **Artists.** Lists are split on `/` `,` `&` `x` `vs` `feat`, and one shared
  artist is enough. Spotify credits remixers and featured artists as artists;
  tags usually put them in the title.
- **Badly tagged files.** A YouTube rip with no artist tag but a title of
  `Artist - Title`, or a file with no tags whose name is
  `[YT2mp3.info] - Artist - Title (3.mp3`, is still read correctly.

Each playlist track comes out as one of three:

| Status | Meaning |
| --- | --- |
| `owned` | A file agrees on title, artist and version |
| `maybe` | The title and artist agree but the version differs, or the file has no artist to confirm it. Listed **with the file**, so you decide |
| `missing` | Nothing in the folder comes close |

`maybe` exists because the costly mistake is a false `owned`: it hides a track
you then never go and get.

### What it writes

From a synthetic test playlist against the reference library — owned tracks
renamed the way Spotify names them, fake remixes of owned tracks, and invented
tracks:

```text
playlist 'My Test Playlist': 55 track(s)
reading tags of 3664 audio file(s) in C:\dev_ws\test-sdm-lib-clone\pioneer-usb-full-clone
maybe    John Beltran, Fakeperson - Belle Isle - Fakeperson Remix
         different version: have 'John Beltran - Belle Isle'
missing  Nonexistent Artist 0 - Invented Track Number 0
missing  Somebody Unrelated - TiK ToK
...
55 track(s): 36 in the folder, 11 missing, 8 maybe (a different version, or a file with no artist tag)
wrote out\playlist-diff\missing_My_Test_Playlist.csv
wrote out\playlist-diff\matched_My_Test_Playlist.csv
```

`TiK ToK` is in the library, by Kesha — so under another artist's name it is
correctly `missing`, not `owned`.

- `missing_<playlist>.csv` — the answer: status, artist, title, album,
  duration, ISRC, Spotify link, and for `maybe` the closest local file and why.
- `matched_<playlist>.csv` — the evidence: every `owned` track and the file it
  matched, plus which reading matched (tags, artist-in-title, filename), so a
  wrong match can be caught rather than trusted.

On the 3,664-file reference library a run takes ~9s, almost all of it reading
tags.

---

## `sdm playlist-export`

Writes a Spotify playlist to CSV — every track, with its artists, album,
release date, duration, ISRC and when it was added.

```ps1
sdm playlist-export "https://open.spotify.com/playlist/<id>"
sdm playlist-export "<link>" --output-csv D:\exports\digging.csv
```

Needs the [Spotify access](#spotify-access) setup, and works for playlists you
own or collaborate on — the same API and the same limit as a `playlist-diff`
link. **Read-only**: it reads the playlist and writes one file.

From a test run against a simulated Spotify API (two pages, seven entries, one
podcast episode and one removed track); a real run first prints the login URL:

```text
read 4 of 7 playlist entries
exported 5 track(s) from 'Digging: Oct / 2026' by Omar; 2 skipped (podcast episodes or tracks no longer on Spotify)
wrote out\playlist-export\Digging_Oct_2026.csv
compare it with a folder, no login needed: sdm playlist-diff "out\playlist-export\Digging_Oct_2026.csv" <folder>
```

The file goes to `out/playlist-export/<playlist name>.csv` unless
`--output-csv` says otherwise (a bare filename stays in that folder, a path is
used as given). Columns, with Exportify's names:

`Track URI`, `Track Name`, `Artist Name(s)`, `Album Name`,
`Album Artist Name(s)`, `Album Release Date`, `Disc Number`, `Track Number`,
`Track Duration (ms)`, `Explicit`, `ISRC`, `Added By`, `Added At`,
`Playlist Name`

- Several artists are joined with a comma and a space — readable in a
  spreadsheet.
- The file carries a UTF-8 byte-order mark so Excel shows accented names
  correctly instead of `SÃºcubo`.
- Local files added to the playlist in the Spotify app are included, with a
  `spotify:local:` URI. Podcast episodes and tracks Spotify has removed are
  skipped and counted.
- **It reads straight back into `playlist-diff`**, with the playlist's real name
  kept for the report filenames.

---

## Layout

```text
src/sdm/
  cli.py              top-level parser; features register their own subcommand
  core/               shared, dependency-light
    track.py          the one Track model
    text.py           title/artist normalization (two strictnesses, on purpose)
    tags.py           ID3/Vorbis/MP4 readers
    grouping.py       union-find, for collapsing pairwise matches into groups
    duplicates.py     the two-stage detector, shared by two features
    fingerprint.py    chromaprint via fpcalc
    fpcalc_fetch.py   borrows an fpcalc for one run when none is installed
    anlz.py           Rekordbox ANLZ reader — beat grids and phrase structure
    playlist.py       playlist model + its CSV format, read and write
    spotify.py        Spotify login (PKCE) and playlist reading
    report.py         CSV/JSON/sidecar writers — how a file is written
    paths.py          out/ and tmp/ resolution — where it is written
  features/
    spotify/          sdm download — deprecated, not registered in cli.py
    catalog/          sdm catalog
    duplicates/       sdm duplicates
    rekordbox/        sdm rekordbox
    analyze/          sdm analyze
    quality/          sdm quality
    playlist_diff/    sdm playlist-diff
    playlist_export/  sdm playlist-export
docs/rekordbox.md     detailed Rekordbox reference
docs/analyze.md       detailed ANLZ / phrase-analysis reference
legacy/               superseded code, not imported
```

Windows-first throughout — examples assume PowerShell and drive letters. There
is no test suite; changes are verified by running the tools against a real
folder or USB. Catalog CSVs and reports are gitignored.

---

## Ideas — not implemented

Sketches of where this could go next. **Nothing below exists.** No command,
flag or module named in this section is real; it is a record of intent, so the
reasoning does not have to be reconstructed later.

### A Rekordbox-like library manager

Today `sdm rekordbox` and `sdm analyze` only *read*. The idea is a manager on
top of those same readers — the parts of Rekordbox worth scripting, without the
GUI:

- **Playlists** — create, rename, reorder, nest, merge, and prune against what
  `sdm duplicates` already finds.
- **Metadata and tags** — bulk edits to title, artist, genre, comment, colour
  and rating, written back to the files *and* to the database so the two do not
  drift.
- **Analysis** — import and export the beat grids and phrase data that
  `core/anlz.py` already parses, rather than re-deriving them.
- **Import/export** — move a library, or a subset of one, between machines and
  USBs as a self-contained bundle.

Playlists are the first slice worth building: they need no new format work.
They live in `master.db` as ordinary rows and `pyrekordbox` can already reach
them, so the only new problem is writing safely.

The constraint that shapes all of it: **`sdm rekordbox` and `sdm analyze` are
read-only by design and stay that way.** Anything that writes is a separate
feature behind its own command, so a bug in a writer can never be reached from
a command whose whole contract is that it touches nothing. Backing up
`master.db` before a write, and refusing to run at all while Rekordbox holds
the database open, belong to the feature rather than to the user's discipline.

### Real audio quality, measured

`sdm quality` currently compares actual sample rate and bitrate against what the
tags claim. The idea is to make the measurement side a real analysis of the
audio:

- **True bitrate**, and the spectral cutoff that betrays a 128 kbps mp3
  re-encoded as a "320", or a lossless container filled with lossy audio.
- **Sample rate and bit depth** as decoded, not as declared.
- **Clipping** — sample peak, true peak, and how many samples are actually
  clipped.
- **Loudness** — EBU R128 integrated LUFS, loudness range, and dynamic range,
  which is what decides whether a track will sit level in a set.

Then diff all of it against what the file's tags and the Rekordbox database
claim about it.

This is the one idea here that is an extension rather than a new feature:
`ffmpeg` already supplies most of it (`ebur128`, `astats`, `volumedetect`) and
`sdm quality` already shells out to `ffprobe`/`ffmpeg`. The part it does not
supply is the spectral analysis behind transcode detection, which needs a real
FFT over decoded audio and is therefore the expensive half — likely opt-in, as
fingerprinting is in `sdm duplicates`.

The premise is the same one `sdm analyze` rests on: a stated bitrate is a claim
by whoever encoded the file, exactly as a `TBPM` tag is a claim against the beat
grid. This would measure it.

### Export to other DJ ecosystems

One library, written onto a USB that something other than Rekordbox can read —
Serato crates or a Traktor collection — carrying across as much as each format
supports: the track list, playlists, cue points, beat grids, key and BPM.

Serato keeps its analysis in `GEOB` ID3 frames on the audio files themselves,
plus `_Serato_` crate files; Traktor keeps a single `collection.nml` XML. Both
are documented by reverse engineering rather than by a specification, which sets
the realistic scope: a **one-way export** that states plainly what did not
survive the trip, not a lossless two-way sync. Phrase structure almost certainly
does not survive it, since nothing else models phrases the way Rekordbox does.

This is a writer, so the same rule applies as above — its own command, never a
flag on a read-only one — and writing `GEOB` frames means modifying the audio
files, which no part of this toolchain does today.

### `sdm dig` — find records that are not in the library yet

Every other command in this tool looks *inward*, at music already owned. This
one looks outward: seed it with what you like, constrain how far off the beaten
track you want to be, and get back tracks, artists, labels and releases worth
listening to — as a report, in the same CSV/JSON shape as everything else.

**Seeds** — any combination, and more than one of each:

- **Genres and styles** — with styles preferred over genres where a source has
  them, since "Deep House" is a useful instruction and "Electronic" is not.
- **Artists, tracks and releases** — including *a file you already own*, which
  is the seed a website cannot take.
- **Labels and catalogue numbers.** Following a label is how most crate-digging
  actually works, and it is the seed most services handle worst.
- **Era, region and scene** — a year range, a country, a city.
- **BPM and key ranges**, which this toolchain already understands from
  `analyze` and `rekordbox`: *find me records that would mix with this one*.

**Tunables:**

- **Underground level** — a floor and ceiling, not a switch. See below; this is
  the hard part.
- **Recency vs. depth** — this month's releases, or a label's back catalogue.
- **Format** — track, EP, LP, album, compilation, single.
- **Availability** — purchasable, streamable, or pressed to vinyl.
- **Wandering distance** — one hop from the seed (same artist, same label) out
  to several (the scene around it).
- **Sources and their weights**, and how many results to return.
- **Exclusions** — anything already in the library, and anything previously
  rejected, so a second run does not return the first run's results.

**The thing only this tool can do:** filter the results against the library it
already knows about — the `catalog` export, the Rekordbox track list, and the
fingerprints from `duplicates`. A discovery site cannot tell you "you already
own this under a different filename, on a compilation, at a different bitrate".
That cross-reference is the feature's reason to exist, and it is also the part
requiring no third-party API at all.

Each result should carry **why it was returned** — the path from seed to
result — or the output is unauditable in exactly the way `catalog` refuses to
be.

#### Feasibility

Workable, but **not by the obvious route**, and the honest summary is that the
best sources are the least accessible. Verify all of this before building on
it — these platforms change their access rules often, and some of the below will
have moved.

| Source | What it gives | Access | Verdict |
| --- | --- | --- | --- |
| **Discogs** | Styles far finer than genres, labels, catalogue numbers, formats, credits, and community *have*/*want* counts | Free API, token, ~60 req/min | **The best foundation.** want/have is a real scarcity signal, and label and credit digging is what the site is built for. No audio |
| **MusicBrainz** | Canonical IDs, release groups typed album/EP/single, artist relationships (producer, remixer, member of) | Free, no key, 1 req/s, User-Agent required | **The spine** — what reconciles the same release across every other source |
| **Last.fm** | Similar artists, tags, and absolute listener/playcount numbers | Free API key | **The best similarity engine still open to new applications.** Absolute listener counts rank better than a relative popularity score |
| **ListenBrainz / AcousticBrainz** | Open listening-derived similarity; BPM, key and mood for millions of recordings | Free; AcousticBrainz is frozen but its dumps are still downloadable | The open replacement for the Spotify endpoints that closed |
| **Spotify** | Popularity 0–100, artist genres, new releases, and `tag:hipster` / `year:` search filters | Free, OAuth client credentials. **Since February 2026** for development-mode apps: the owner needs Premium, 5 users per app, search returns at most 10 results per page, and track `popularity` and artist `popularity`/`followers` are removed | Narrower than below suggests — the popularity signal this row leads with is gone for new apps. Re-check before building |
| **Beatport** | The DJ-relevant genre taxonomy, release dates, charts | Partner-gated OAuth | Uncertain. Assume unavailable until approved |
| **SoundCloud** | Unofficial edits, dubs and pre-release material found nowhere else | New app registration has been closed for years | Assume unavailable |
| **Bandcamp** | The most underground catalogue of the lot, and directly purchasable | No public API; scraping the site is against its terms | **The widest gap between value and access.** Treat as a manual step |

**The Spotify catch, and it is the important one.** The endpoint this feature
would obviously be built on — `/v1/recommendations`, seeded with genres, artists
and tracks, tuned with `min_popularity`/`max_popularity` — was deprecated for
new applications in late 2024, along with Related Artists, Audio Features and
Audio Analysis. Applications that already had extended access kept it; a new one
does not get it. So the single closest-fitting API in existence is closed, and
what remains is search (which does support `tag:hipster`, meaning the bottom
10% of popularity — a genuine underground filter), plus per-track and
per-artist popularity. Plan around Discogs, MusicBrainz and Last.fm, and treat
Spotify as a lookup for availability and popularity rather than as the engine.

**Sites like [chosic.com](https://www.chosic.com/) are the exception that proves
this, not a way around it.** They do exactly what this feature describes —
seeded recommendations with tunable parameters, genre lookup per track, links
straight to Spotify — and they still work in a browser. That is most likely
because they predate the cutoff and kept the access a new application cannot
get. So a working site is evidence the door is closed behind it, not that it is
open. Depending on one programmatically means scraping: no stability contract,
breaks on any redesign, generally against the site's terms, and it borrows an
API grant that belongs to someone else. Use them as **research tools and as a
model** — their parameter sets are a good specification to copy — not as a
backend.

**"Underground" is not a number, and pretending otherwise is the trap.** No
single field means it. Spotify popularity is relative and decays with time;
Last.fm listener counts are absolute but skew to what Last.fm's users scrobble;
Discogs want/have measures collector demand for physical copies, which is a
different thing again. And the scale is genre-dependent — 5,000 listeners is
obscure in house and substantial in modular ambient. The workable version is a
**composite score expressed as a percentile within the seed's own genre**, built
from whichever signals a given result actually has, with the inputs shown in the
report rather than hidden behind one number. Getting this right is most of the
work, and it is a judgement call being encoded, not a measurement.

**What it costs architecturally**, since this is unlike every existing feature:

- It is **network-first**. Everything else here reads local files, so this is
  the first feature whose results are not reproducible from the inputs alone.
- It needs a **persistent cache**, which the current path rules have no place
  for: `out/` is reports and `tmp/` is scratch deleted on exit. A third root, or
  an explicit `--cache-dir`, is a decision to make before writing code — rate
  limits of 1 req/s make an uncached re-run unusable.
- It needs **credentials**, which nothing in this repo handles today.
  Environment variables, never committed, and the command should degrade to the
  sources it has keys for rather than failing.
- Each source is an **adapter behind one interface**, so a closed API degrades
  the results instead of breaking the command — which, given the table above, is
  the normal case rather than the exception.
- It stays **read-only against every service**: it queries and reports, and
  never posts, follows, or modifies a playlist.

Start with Discogs plus the local-library cross-reference. That combination
needs one free token, answers the "what am I missing from this label" question
immediately, and is the half that no website can do.

### Genre and style enrichment

Separate from `dig`, and useful to more of the toolchain than `dig` is: fill in
what each track in the **local** library actually is. Genre tags on a real
collection are patchy, inconsistent between rips, and frequently just wrong —
`sdm catalog` reports what the tags say, and the tags often say nothing.

Look each track up by artist and title and attach genres, styles and tags from
the sources that have them, written to a report and — separately, and only on
request — back to the files. Worth knowing before designing it:

- **Spotify's genres are attached to artists, not tracks.** Anything presenting
  a "track genre" from Spotify is showing you the artist's genre list. For an
  artist who works across styles, that is close to useless at track level.
- **Discogs styles are the ones that matter here**, because they are per release
  and granular in exactly the direction a DJ needs — "Deep House", "Electro",
  "Drum n Bass" rather than "Electronic".
- **Last.fm tags** are crowd-sourced, so they are broad, occasionally nonsense,
  and much better at scenes and moods than any official taxonomy.
- **MusicBrainz genres** are the cleanest to reconcile against, being tied to
  the same IDs everything else can be keyed on.
- Every Noise at Once, long the reference map of Spotify's genre space, stopped
  being maintained after its author left Spotify. Do not build on it.

This is also **a prerequisite for `dig`'s underground scoring**, not merely a
companion to it: ranking a result as a percentile *within its genre* requires
knowing the genre of the things being compared, including the ones already
owned. Two ideas, but this one comes first.

Writing tags back to files is a writer, with everything that implies above: its
own command, never an implicit step in a read-only one.
