"""`sdm catalog` — export and audit a folder of MP3s."""
from __future__ import annotations

import argparse


def add_parser(subparsers, parents=()) -> argparse.ArgumentParser:
    p = subparsers.add_parser(
        "catalog",
        parents=list(parents),
        help="Catalog a music folder to CSV and cross-validate the export.",
        description="Walk a folder of MP3s, write a CSV catalog plus a path "
                    "sidecar, report likely duplicates, and verify the export "
                    "against the directory.",
    )
    p.add_argument("directory", help="Folder of MP3s to catalog.")
    p.add_argument("--output-csv", default=None,
                   help="Destination CSV (default: "
                        "<out-dir>/catalog/mp3_file_list_<folder>.csv). A bare "
                        "filename lands in that directory; a path with a "
                        "directory component is used as given. The "
                        "cross-validation sidecar name is derived from it.")
    p.set_defaults(handler=_run)
    return p


def _run(args: argparse.Namespace) -> int:
    from sdm.features.catalog.exporter import run

    return run(args.directory, args.output_csv)
