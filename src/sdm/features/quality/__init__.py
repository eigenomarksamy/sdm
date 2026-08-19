"""`sdm quality` — compare real audio properties against what the tags claim.

Decodes each file with ffprobe/ffmpeg to measure its actual sample rate and
bitrate, then diffs those against the ID3 metadata. Large positive differences
mean the tags overstate the file's quality — the signature of a re-encode.
"""
from __future__ import annotations

import argparse


def add_parser(subparsers) -> argparse.ArgumentParser:
    p = subparsers.add_parser(
        "quality",
        help="Check whether files' real bitrate matches their tags.",
        description="Measure actual sample rate and bitrate with ffprobe/ffmpeg "
                    "and diff against the values in the ID3 tags. "
                    "Requires ffmpeg and ffprobe on PATH.",
    )
    p.add_argument("directory", help="Folder of MP3s to check (not recursive).")
    p.add_argument("--output-csv", default=None,
                   help="Write the report to CSV instead of printing it.")
    p.set_defaults(handler=_run)
    return p


def _run(args: argparse.Namespace) -> int:
    from sdm.features.quality.analyzer import compare_and_report

    df = compare_and_report(args.directory)

    if args.output_csv:
        df.to_csv(args.output_csv, index=False)
        print(f"wrote {args.output_csv}")
    else:
        print(df.to_string(index=False))

    return 0
