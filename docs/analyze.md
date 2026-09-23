# `sdm analyze`

Reference for the analyze feature: a read-only tool that reads **Rekordbox's own
analysis** off a Pioneer USB — the beat grid it computed and the phrase
structure it detected for every track.

> **Read-only by design.** This tool opens the USB's analysis files and writes
> reports elsewhere. Nothing on the USB is written.

## Why this exists

Rekordbox writes far more beside a track than the exported database holds. Under
`PIONEER/USBANLZ/P<nnn>/<hash>/` there is an analysis file set per track —
`ANLZ0000.DAT`, `.EXT`, `.2EX` — carrying the beat grid, the phrase structure,
and several waveform renderings.

None of that is in the audio file's tags, and none of it is in the exported
database. This is the only way to reach it without the desktop application, and
it is the one feature here that needs **no Rekordbox install and no `master.db`**
— which is precisely the case `sdm rekordbox` handles worst.

## What it reads

| Tag | What it is | Coverage on the reference USB (3,665 tracks) |
| --- | --- | --- |
| `PPTH` | the track's path as Rekordbox recorded it | 3,665 |
| `PQTZ` | beat grid — per beat: position in bar, tempo, time | 3,655 (99.7%) |
| `PQT2` | extended grid; its header carries a track BPM | fallback only |
| `PSSI` | phrase structure | 3,646 (99.5%) |

Waveform tags (`PWAV`, `PWV2`–`PWV7`, `PWVC`) are **deliberately not parsed**.
They are almost all of the bytes on disk and nothing here renders them: skipping
them takes a full-library scan from 8m28s to 49s. `core/anlz.py` names them in
`WAVEFORM_TAGS` so the door stays open.

Three things the format does **not** give you:

- **Title and artist.** ANLZ records a *path*, never a name. The first two
  columns of `analysis.csv` therefore come from the audio file's own tags, via
  `core.tags.read_title_artist` — which means they are only available for tracks
  whose file resolved, and read "Unknown" for a file that carries no tags. On the
  reference USB 3,627 of 3,665 have both; the rest are untagged WAV and AIFF
  samples. It costs about a second on a full run: mutagen reads the tag header,
  not the audio, and the scan is I/O-bound regardless.
- **Musical key.** It is not in ANLZ at all — Rekordbox keeps it in the
  database, so `sdm rekordbox` remains the only source.
- **Cue points.** These *are* in the format (`PCOB`/`PCO2`) and are not parsed,
  because the reference library of 3,665 tracks carries exactly one hot cue and
  no memory cues. A cue reader would be untested code serving nothing. Add it
  when a library actually has cues in it.

## Usage

```ps1
pip install -e ".[analyze]"

sdm analyze D:/                       # USB mounted at D:
sdm analyze D:/ --limit 50            # sample before committing to a full scan
sdm analyze D:/ --export-beats        # also dump every beat of every grid
```

The path may be the USB root or a `PIONEER/USBANLZ` directory directly.

| Flag | Default | Meaning |
| --- | --- | --- |
| `usb_path` | — | USB mount path, or a `USBANLZ` directory. |
| `--output-dir` | `<out-dir>/analyze/` | Where reports go. |
| `--limit N` | — | Stop after N tracks. |
| `--export-beats` | off | Also write `beats.csv` — millions of rows on a full library. |

## Output

- **`analysis.csv`** — one row per track: title, artist, the recorded and
  resolved file paths, grid BPM, whether the tempo varies, beat count, first
  downbeat, mood, phrase count, `intro_end_ms`, `outro_start_ms`, and any
  warnings.
- **`phrases.csv`** — one row per phrase: label, kind, start/end beat, length in
  **bars**, start/end time in ms, and the fill-in beat where there is one.
- **`analysis.json`** — the same data nested per track, minus the beat grid.
- **`beats.csv`** — only with `--export-beats`: every beat, its position in the
  bar, the tempo in force, and its time.

`intro_end_ms` and `outro_start_ms` are plain readings of the phrase list — where
the last Intro phrase ends and the first Outro phrase begins. They are not
inferred mix points.

## Phrase labels

Rekordbox analyses a track under one of three **moods**, and the mood decides
what a phrase kind is called. On the reference USB: high 2,314, mid 1,251, low
81.

- **Mid and low** name phrases by kind alone: Intro, Verse 1–6, Bridge, Chorus,
  Outro.
- **High** uses fewer kinds and carries the variant in separate flag fields —
  `k1` selects the second form of Intro, Chorus and Outro; `k2`/`k3` select which
  of the three Up phrases this is. Its labels are Intro 1/2, Up 1/2/3, Down,
  Chorus 1/2, Outro 1/2.

This yields exactly 20 labels, and across 76,118 phrases on the reference
library **every phrase resolved to one of them** — no unknowns. An unrecognized
kind is reported as `Unknown (mood M, kind K)` rather than guessed at, so a
format change shows up in the output instead of hiding behind a plausible name.

> The *structure* of this scheme is confirmed by the data — which flags appear on
> which kinds, and that high mood uses only kinds {1, 2, 3, 5, 6}. The *names*
> come from the published format analysis and have not been checked against what
> Rekordbox's own UI displays for a given track. If a label ever looks wrong, the
> raw `kind` is in the CSV beside it.

## Measured baseline

Use these as the regression check — `test-sdm-lib-clone/pioneer-usb-full-clone`,
3,665 tracks:

```text
49s wall warm, ~1m15s cold (the scan is I/O-bound; it reads ~880MB of .DAT/.EXT)
beat grid        3,655 (99.7%)     phrase structure  3,646 (99.5%)
mood             high 2,314 / mid 1,251 / low 81
phrases          76,118 total, median 20/track, 0 unknown labels
variable tempo   2 tracks
warnings         119 recovered beat grids, 1 unresolved audio path
```

A run on this USB reporting materially different numbers means something changed.

### Why the grid BPM is worth having

Cross-checked against the `TBPM` tag on the 1,814 tracks that carry one:

| Agreement | Tracks |
| --- | --- |
| within 0.05 BPM | 1,374 (75.7%) |
| disagree by > 0.5 BPM | 313 (17.3%) |

Of those 313, **97 are tags at exactly half the real tempo**, 55 are off by ×1.33,
5 by ×0.75, 1 at double — and 155 are simply wrong (Moby's *Thousand* is tagged
136 against a measured grid of 137.29). Where they differ, the beat grid is
Rekordbox's own measurement and the tag is a claim.

## Two parser workarounds, and why they are load-bearing

`core/anlz.py` walks the ANLZ tag chain itself and parses one tag at a time,
rather than calling `AnlzFile.parse_file`. The binary layouts still come from
`pyrekordbox.anlz` — nothing here re-describes the format — but the
all-or-nothing parse had to go:

1. **`PQTZ`'s over-strict constant.** pyrekordbox declares the tag's second
   header word `Const(0x00080000)`. Only the high half is actually fixed. 119 of
   3,665 files carry `0x0008xxxx` there, and pyrekordbox therefore discards the
   whole `.DAT` — beat grid included. Read as a plain integer, all 119 produce
   grids that pass a sanity check (beats number 1–4, times increase), which is
   what takes coverage from 3,541 to 3,655. Those rows carry a warning saying so.
2. **Unknown tags.** Newer Rekordbox versions emit `PVDI` and `PVB2`, which
   pyrekordbox has never seen. Walking the chain by each tag's declared length
   means an unknown tag costs that tag and nothing else.

Relaxing a constant means giving up the check it was performing, so
`_looks_like_a_grid` earns the result back before it is trusted. Across the whole
library no beat grid — recovered or not — has two beats at the same timestamp.

## A note on `features/rekordbox/analysis.py`

That module predates this one and is **wrong, not merely superseded**. It
searches for `PSGL` and `PKEY` tags; neither exists in the ANLZ format. Its BPM
extractor brute-forces byte offsets until a float lands between 40 and 200. It is
imported by nothing. Do not take it as a reference for the format — this feature
is the reference.
