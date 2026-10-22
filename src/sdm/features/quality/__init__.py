"""`sdm quality` — what each file's audio really is, beside what it claims to be.

Decodes every audio file under a folder or a Rekordbox USB and measures what a
header cannot be trusted for: the true average bitrate, the spectral cutoff
that betrays a transcode, sample rate and bit depth as decoded, EBU R128
loudness, true peak, clipping and stereo correlation. Each row puts those next
to what the file's own header and tags claim and, when a Rekordbox database can
be read, what Rekordbox recorded — and says where they disagree.

The premise is `sdm analyze`'s: a stated bitrate is a claim by whoever encoded
the file, exactly as a TBPM tag is a claim against the beat grid.

Read-only: files are decoded, never written. Needs ffmpeg and ffprobe on PATH
and numpy (`pip install -e ".[quality]"`); the Rekordbox columns also need
pyrekordbox and are left blank without it.
"""
from __future__ import annotations

import argparse


def add_parser(subparsers, parents=()) -> argparse.ArgumentParser:
    p = subparsers.add_parser(
        "quality",
        parents=list(parents),
        help="Measure audio quality and compare it with what the metadata claims.",
        description="Decode every audio file under a folder or Rekordbox USB and "
                    "measure its true bitrate, spectral cutoff (transcode "
                    "detection), sample rate, bit depth, loudness (EBU R128), "
                    "true peak and clipping, next to what the file's tags and "
                    "the Rekordbox database claim. Read-only. Requires ffmpeg "
                    "and ffprobe on PATH.",
    )
    p.add_argument("directory",
                   help="Folder or Rekordbox USB to check, searched recursively. "
                        "Every audio type: mp3, m4a, flac, aiff, wav, ogg.")
    # This takes a mandatory value, unlike `rekordbox --export-csv`: with a
    # positional `directory` in the same parser, an optional-value flag would
    # swallow it (`sdm quality --output-csv F:/Songs` would read the folder as
    # the CSV name and then fail for a missing directory).
    p.add_argument("--output-csv", default=None, metavar="PATH",
                   help="Where to write the report (default: "
                        "<out-dir>/quality/quality_<folder>.csv). A bare filename "
                        "lands in <out-dir>/quality/; a path with a directory "
                        "component is used as given.")
    p.add_argument("--jobs", type=int, default=None, metavar="N",
                   help="Files to measure at once (default: half the CPU cores, "
                        "at most 8).")
    p.add_argument("--limit", type=int, default=None, metavar="N",
                   help="Stop after the first N files. For sampling a library "
                        "before the full run, which takes ~2s of CPU per track.")
    p.add_argument("--db-path", default=None, metavar="PATH",
                   help="Read Rekordbox's claims from this master.db instead of "
                        "the local Rekordbox library's.")
    p.add_argument("--no-rekordbox", action="store_true",
                   help="Do not read any Rekordbox database; compare against the "
                        "files' own metadata only.")
    p.set_defaults(handler=_run)
    return p


def _run(args: argparse.Namespace) -> int:
    from sdm.features.quality.command import run

    return run(args)
