# sdm

A personal music-library toolchain for a DJ workflow, behind one command.

It covers a single pipeline — *acquire, catalog, reconcile* — split into isolated
features that share a small common core:

```text
  sdm download        sdm catalog          sdm rekordbox        sdm quality
  acquire from        catalog & audit      reconcile with       verify real
  Spotify             local MP3s           Rekordbox/USB        audio quality
       \                   |                     |                  /
        \__________________ sdm.core ___________________________ ___/
             track model · normalization · tags · grouping · reports
```

Each feature is self-contained: it may use `sdm.core`, never a sibling. Heavy
dependencies are optional extras loaded only when their subcommand runs, so
`sdm download` works on a machine with no Rekordbox and no ffmpeg.

## Install

```ps1
pip install -e .              # base: download + catalog
pip install -e ".[all]"       # everything
pip install -e ".[rekordbox]" # + Rekordbox reading and fingerprinting
pip install -e ".[quality]"   # + the bitrate checker
```

Requires Python 3.9+. Two features need external binaries on PATH:
`ffmpeg`/`ffprobe` for `sdm quality`, and `fpcalc`
([chromaprint](https://acoustid.org/chromaprint)) for fingerprint-based
duplicate detection.

```ps1
sdm --help
sdm <command> --help
```

## Where output goes

Every generated report lands under one root, in a folder named for the feature
that produced it:

```text
./out/
  catalog/     mp3_file_list_<folder>.csv + _x_val.txt sidecar
  rekordbox/   duplicates.csv, duplicates.json, tracks.csv
  quality/     the bitrate report, when --output-csv is given
  logs/        download.log
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
goes wherever `sdm download --output` points, untouched by `--out-dir`.

---

## `sdm download`

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
| `--dry-run`, `-n` | off | Simulate a run |
| `--disable-log` | off | Suppress logging (otherwise `out/logs/download.log`) |

`--sync` and `--run-pp` are accepted by the parser but not yet wired up.

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

## `sdm quality`

Decodes each file with `ffprobe`/`ffmpeg` to measure its *actual* sample rate
and bitrate, then diffs those against what the ID3 tags claim — useful for
spotting re-encoded files passed off as high quality.

```ps1
sdm quality "F:/Songs" --output-csv quality_report.csv
```

---

## Layout

```text
src/sdm/
  cli.py              top-level parser; features register their own subcommand
  core/               shared, dependency-light
    track.py          the one Track model
    text.py           title/artist normalization (two strictnesses, on purpose)
    tags.py           ID3/Vorbis readers
    grouping.py       union-find, for collapsing pairwise matches into groups
    report.py         CSV/JSON/sidecar writers — how a file is written
    paths.py          out/ and tmp/ resolution — where it is written
  features/
    spotify/          sdm download
    catalog/          sdm catalog
    rekordbox/        sdm rekordbox
    quality/          sdm quality
docs/rekordbox.md     detailed Rekordbox reference
legacy/               superseded code, not imported
```

Windows-first throughout — examples assume PowerShell and drive letters. There
is no test suite; changes are verified by running the tools against a real
folder or USB. Catalog CSVs and reports are gitignored.
