"""`sdm catalog` — export and audit a folder of MP3s.

`--missing-metadata` switches the command to a second, narrower job: list the
tracks whose tags have no title, no artist, or neither. It is a flag rather than
a nested subcommand so `sdm catalog <dir>` keeps parsing — argparse would read
the folder as a subcommand name.
"""
from __future__ import annotations

import argparse


def add_parser(subparsers, parents=()) -> argparse.ArgumentParser:
    p = subparsers.add_parser(
        "catalog",
        parents=list(parents),
        help="Catalog a music folder to CSV and cross-validate the export.",
        description="Walk a folder of MP3s, write a CSV catalog plus a path "
                    "sidecar, report likely duplicates, and verify the export "
                    "against the directory. With --missing-metadata, instead "
                    "list the tracks missing a title, an artist, or both.",
    )
    p.add_argument("directory", help="Folder of MP3s to catalog.")
    p.add_argument("--output-csv", default=None,
                   help="Destination CSV (default: "
                        "<out-dir>/catalog/mp3_file_list_<folder>.csv, or "
                        "missing_metadata_<folder>.csv with --missing-metadata). "
                        "A bare filename lands in that directory; a path with a "
                        "directory component is used as given. The "
                        "cross-validation sidecar name is derived from it.")
    p.add_argument("--missing-metadata", action="store_true",
                   help="Skip the export and list only the tracks whose tags "
                        "lack a title, an artist, or both. Covers every audio "
                        "format, not just MP3, and tells an untagged file from "
                        "one that could not be read.")
    p.set_defaults(handler=_run)
    return p


def _run(args: argparse.Namespace) -> int:
    if args.missing_metadata:
        from sdm.features.catalog.missing_metadata import run as run_missing

        return run_missing(args.directory, args.output_csv)

    from sdm.features.catalog.exporter import run

    return run(args.directory, args.output_csv)
