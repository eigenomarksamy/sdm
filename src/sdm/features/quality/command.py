"""Runs the `sdm quality` subcommand.

Walk -> for each file, what its metadata claims (its own header and tags, and
Rekordbox's database when one can be read), what its audio measures, and where
the two disagree -> one CSV row per file, measured and claimed side by side.

Files are measured in parallel, because one decode is ~2 s and a library is
thousands of them. Threads are enough: the work is an ffmpeg process plus numpy
calls that release the GIL (processes measured only 8% faster). The main thread
waits on them with a timeout rather than blocking outright, so Ctrl-C — and
`sdm web`'s cancel, which arrives as the same KeyboardInterrupt — is seen
within half a second, and then `measure.Decoders` stops every decode still in
flight; see there for why the signal alone is not enough.

Read-only: every file is opened for reading and nothing is written but the
report.
"""
from __future__ import annotations

import argparse
import os
import shutil
import statistics
import sys
import time
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from typing import Callable, Iterable, Optional

from sdm.core.paths import resolve_output
from sdm.core.rekordbox_db import RekordboxFile, load_files
from sdm.core.report import write_csv
from sdm.core.tags import AudioHeader, read_audio_header, read_title_artist
from sdm.core.track import iter_audio_files
from sdm.features.quality.claims import RekordboxIndex
from sdm.features.quality.compare import Flag, clip_rate_pct, flags
from sdm.features.quality.measure import Decoders, Measurement, measure

#: Print a progress line every this many files: often enough for `sdm web`'s
#: bar to move, rarely enough that a library run is not thousands of lines.
PROGRESS_EVERY = 25

#: Grouped by aspect, measured value first and then the claims about it, so
#: that "what it is" and "what it says" sit next to each other in any table.
#: No prefix: measured from the audio. `meta_`: the file's own header and tags.
#: `rb_`: Rekordbox's database.
HEADER = (
    "title",
    "artist",
    "file_path",
    "codec",
    "encoder",
    "bitrate_kbps",
    "meta_bitrate_kbps",
    "meta_bitrate_mode",
    "rb_bitrate_kbps",
    "cutoff_khz",
    "cutoff_sharp",
    "sample_rate",
    "meta_sample_rate",
    "rb_sample_rate",
    "bit_depth",
    "meta_bit_depth",
    "rb_bit_depth",
    "duration_s",
    "meta_duration_s",
    "rb_duration_s",
    "integrated_lufs",
    "loudness_range_lu",
    "replaygain_db",
    "meta_replaygain_db",
    "true_peak_dbtp",
    "sample_peak_dbfs",
    "plr_db",
    "clipped_samples",
    "clip_rate_pct",
    "channels",
    "stereo_correlation",
    "decode_errors",
    "rb_match",
    # The same flags twice: `issues` is each one's kind, for filtering and
    # counting ("transcode?; clipping"), `flags` the sentences, in the same order.
    "issues",
    "flags",
    "error",
)


@dataclass(frozen=True)
class FileResult:
    path: str
    title: str
    artist: str
    meta: AudioHeader
    measured: Measurement
    rb: Optional[RekordboxFile]
    rb_match: Optional[str]
    flags: list[Flag]


def run(args: argparse.Namespace) -> int:
    directory = args.directory
    if not os.path.isdir(directory):
        print(f"error: not a directory: {directory}", file=sys.stderr)
        return 2

    missing = [tool for tool in ("ffmpeg", "ffprobe") if shutil.which(tool) is None]
    if missing:
        print(f"error: {' and '.join(missing)} not found on PATH. Install ffmpeg "
              "(https://ffmpeg.org/download.html) and try again.", file=sys.stderr)
        return 1

    if args.no_rekordbox:
        rb_index = None
    else:
        rb_index = _load_rekordbox(args.db_path)
        if rb_index is None and args.db_path:
            return 1  # asked for by name, so not quietly skipped

    files = sorted(iter_audio_files(directory))
    if args.limit:
        files = files[:args.limit]
    print(f"scanning {directory}: {len(files)} audio file(s)")

    jobs = args.jobs or default_jobs()
    results: list[FileResult] = []
    started = time.monotonic()

    def collect(result: FileResult) -> None:
        # Nothing here prints a file name: see the failures below.
        results.append(result)
        if len(results) % PROGRESS_EVERY == 0 or len(results) == len(files):
            print(f"  measured {len(results)}/{len(files)}")

    decoders = Decoders()
    try:
        _run_parallel(files, lambda path: _examine(path, rb_index, decoders), jobs, collect,
                      on_abort=decoders.stop)
    except RuntimeError as exc:
        # ffmpeg or ffprobe vanished mid-run; every remaining file would fail the same way.
        print(f"error: {exc}", file=sys.stderr)
        return 1

    results.sort(key=lambda r: r.path)
    out_path = resolve_output(args.output_csv, "quality", f"quality_{_label(directory)}.csv")
    write_csv(out_path, HEADER, (_row(r) for r in results))

    # File names are printed only once the report is safe on disk. A redirected
    # stdout on Windows is cp1252 and raises on a name outside it (see
    # CLAUDE.md, "Planned fixes"); before the write, that would lose the run.
    for r in results:
        if r.measured.error:
            print(f"  could not measure {r.path}: {r.measured.error}")
    _summarize(results, time.monotonic() - started, rb_index)
    print(f"wrote {out_path}")
    return 0


def default_jobs() -> int:
    """Half the logical CPUs, at most 8.

    Each job is one ffmpeg decode, single-threaded, so more jobs than cores
    only adds contention; past ~8 the disk, not the CPU, sets the pace on a
    USB stick.
    """
    return max(1, min(8, (os.cpu_count() or 2) // 2))


def _load_rekordbox(db_path: Optional[str]) -> Optional[RekordboxIndex]:
    """The database's claims, or None — with a line saying why — if it cannot be read."""
    source = db_path or "the local Rekordbox library"
    try:
        rows = load_files(db_path)
    except ImportError:
        print('rekordbox: skipped - pyrekordbox is not installed (pip install -e ".[rekordbox]")')
        return None
    except Exception as exc:
        print(f"rekordbox: skipped - could not read {source}: {exc}")
        return None
    print(f"rekordbox: {len(rows)} file(s) recorded in {source}")
    return RekordboxIndex(rows)


def _examine(path: str, rb_index: Optional[RekordboxIndex], decoders: Decoders) -> FileResult:
    """Everything about one file. Runs on a worker thread."""
    title, artist = read_title_artist(path)
    meta = read_audio_header(path)
    rb, how = rb_index.find(path) if rb_index else (None, None)
    measured = measure(path, decoders)
    return FileResult(path, title, artist, meta, measured, rb, how, flags(measured, meta, rb))


def _run_parallel(items: Iterable[str], fn: Callable[[str], FileResult], jobs: int,
                  collect: Callable[[FileResult], None], *,
                  on_abort: Callable[[], None]) -> None:
    """Run `fn` over `items` on `jobs` threads, handing each result to `collect`.

    Only `2 * jobs` are queued at a time, and if anything interrupts the loop —
    Ctrl-C, a cancel, an error — `on_abort` runs before the pool is waited for,
    so the threads still busy end now rather than after their file.
    """
    pending = iter(items)
    pool = ThreadPoolExecutor(max_workers=jobs)
    running: set[Future] = set()
    try:
        for _ in range(2 * jobs):
            item = next(pending, None)
            if item is None:
                break
            running.add(pool.submit(fn, item))
        while running:
            done, running = wait(running, timeout=0.5, return_when=FIRST_COMPLETED)
            for future in done:
                collect(future.result())
                item = next(pending, None)
                if item is not None:
                    running.add(pool.submit(fn, item))
    except BaseException:
        on_abort()
        raise
    finally:
        pool.shutdown(wait=True, cancel_futures=True)


def _row(r: FileResult) -> list:
    m, meta, rb = r.measured, r.meta, r.rb
    replaygain = -18.0 - m.integrated_lufs if m.integrated_lufs is not None else None
    plr = (m.true_peak_dbtp - m.integrated_lufs
           if m.true_peak_dbtp is not None and m.integrated_lufs is not None else None)
    return [
        r.title,
        r.artist,
        r.path,
        m.codec or "",
        meta.encoder or "",
        _num(m.bitrate_kbps, 1),
        _num(meta.bitrate_kbps, 1),
        meta.bitrate_mode or "",
        _num(rb.bitrate_kbps if rb else None),
        _num(m.cutoff_hz / 1000 if m.cutoff_hz else None, 2),
        ("yes" if m.cutoff_sharp else "no") if m.cutoff_hz else "",
        _num(m.sample_rate),
        _num(meta.sample_rate),
        _num(rb.sample_rate if rb else None),
        _num(m.bit_depth),
        _num(meta.bit_depth),
        _num(rb.bit_depth if rb else None),
        _num(m.duration_seconds, 2),
        _num(meta.duration_seconds, 2),
        _num(rb.duration_seconds if rb else None),
        _num(m.integrated_lufs, 1),
        _num(m.loudness_range_lu, 1),
        _num(replaygain, 1),
        _num(meta.replaygain_db, 2),
        _num(m.true_peak_dbtp, 1),
        _num(m.sample_peak_dbfs, 2),
        _num(plr, 1),
        _num(m.clipped_samples),
        _num(clip_rate_pct(m), 4),
        _num(m.channels),
        # Four places, not three: "1.000" would also show for 0.9995, which is
        # not mono and not flagged as such.
        _num(m.stereo_correlation, 4),
        _num(m.decode_errors),
        r.rb_match or "",
        "; ".join(f.kind for f in r.flags),
        "; ".join(f.text for f in r.flags),
        m.error or meta.error or "",
    ]


def _summarize(results: list[FileResult], elapsed: float,
               rb_index: Optional[RekordboxIndex]) -> None:
    measured = [r for r in results if not r.measured.error]
    failed = len(results) - len(measured)
    print(f"measured {len(measured)} of {len(results)} file(s) in {_duration(elapsed)}"
          + (f" - {failed} could not be decoded" if failed else ""))
    if not measured:
        return

    codecs = Counter(r.measured.codec for r in measured)
    print("  codecs: " + ", ".join(f"{c} {n}" for c, n in codecs.most_common()))

    loudness = [r.measured.integrated_lufs for r in measured if r.measured.integrated_lufs is not None]
    if loudness:
        print(f"  loudness: median {statistics.median(loudness):.1f} LUFS, "
              f"quietest {min(loudness):.1f}, loudest {max(loudness):.1f}")
    over = sum(1 for r in measured if (r.measured.true_peak_dbtp or -99) > 0)
    print(f"  true peak above 0 dBTP: {over} file(s)")

    if rb_index is not None:
        matched = Counter(r.rb_match for r in results if r.rb_match)
        print(f"  rekordbox: {sum(matched.values())} of {len(results)} file(s) matched ("
              + ", ".join(f"{how} {n}" for how, n in matched.most_common()) + ")")

    kinds = Counter(f.kind for r in results for f in r.flags)
    flagged = sum(1 for r in results if r.flags)
    print(f"  flagged: {flagged} file(s)")
    for kind, count in kinds.most_common():
        print(f"    {kind:<24} {count}")


def _label(directory: str) -> str:
    """The report's name for a folder; a drive root ("D:/") has no basename to use."""
    name = os.path.basename(os.path.normpath(directory))
    if name:
        return name
    drive = os.path.splitdrive(os.path.abspath(directory))[0]
    return drive.rstrip(":\\/") or "library"


def _num(value, digits: int = 0) -> str:
    if value is None:
        return ""
    if digits == 0:
        return str(int(round(value)))
    return f"{value:.{digits}f}"


def _duration(seconds: float) -> str:
    minutes, secs = divmod(int(round(seconds)), 60)
    return f"{minutes}m{secs:02d}s" if minutes else f"{secs}s"
