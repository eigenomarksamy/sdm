"""`sdm quality` — compare real audio properties against what the tags claim.

Decodes each file with ffprobe/ffmpeg to measure its actual sample rate and
bitrate, then diffs those against the ID3 metadata. Large positive differences
mean the tags overstate the file's quality — the signature of a re-encode.
"""
from __future__ import annotations

import argparse


def add_parser(subparsers, parents=()) -> argparse.ArgumentParser:
    p = subparsers.add_parser(
        "quality",
        parents=list(parents),
        help="Check whether files' real bitrate matches their tags.",
        description="Measure actual sample rate and bitrate with ffprobe/ffmpeg "
                    "and diff against the values in the ID3 tags. "
                    "Requires ffmpeg and ffprobe on PATH.",
    )
    p.add_argument("directory", help="Folder of MP3s to check (not recursive).")
    # This takes a mandatory value, unlike `rekordbox --export-csv`: with a
    # positional `directory` in the same parser, an optional-value flag would
    # swallow it (`sdm quality --output-csv F:/Songs` would read the folder as
    # the CSV name and then fail for a missing directory).
    p.add_argument("--output-csv", default=None, metavar="PATH",
                   help="Write the report to CSV instead of printing it. "
                        "A bare filename lands in <out-dir>/quality/; a path "
                        "with a directory component is used as given.")
    p.set_defaults(handler=_run)
    return p


def _run(args: argparse.Namespace) -> int:
    import os

    from sdm.core.paths import resolve_output
    from sdm.features.quality.analyzer import compare_and_report

    df = compare_and_report(args.directory)

    # Printing stays the default; only an explicit --output-csv writes a file.
    if args.output_csv is None:
        print(df.to_string(index=False))
        return 0

    folder_name = os.path.basename(os.path.normpath(args.directory))
    out_path = resolve_output(args.output_csv, "quality", f"quality_{folder_name}.csv")
    df.to_csv(out_path, index=False)
    print(f"wrote {out_path}")

    return 0
