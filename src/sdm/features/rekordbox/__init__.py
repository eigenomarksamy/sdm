"""`sdm rekordbox` — read a Rekordbox library and report duplicates.

Read-only by design: this feature never writes to the USB or to the Rekordbox
database. Output goes only to `--output-dir` or `--export-csv`.
"""
from __future__ import annotations

import argparse


def add_parser(subparsers) -> argparse.ArgumentParser:
    p = subparsers.add_parser(
        "rekordbox",
        help="Read a Rekordbox library; export metadata or report duplicates.",
        description="Read a Rekordbox USB or database (read-only) and either "
                    "export track metadata or report duplicate tracks.",
    )
    p.add_argument("--usb-path", help="Mount path of the Rekordbox USB (e.g. E:/)")
    p.add_argument("--db-path", help="Direct path to master.db (overrides --usb-path)")
    p.add_argument("--output-dir", default="./out", help="Where to write reports (default: ./out)")

    p.add_argument(
        "--export-csv",
        metavar="PATH",
        help="Export track metadata to CSV (title, artist, bpm, time, key) and exit.",
    )

    p.add_argument(
        "--duplicates-by-name",
        action="store_true",
        help="Report duplicates by matching (title, artist) only; "
             "skips the BPM/key/fingerprint pipeline.",
    )

    p.add_argument("--bpm-tolerance", type=float, default=0.5)
    p.add_argument("--duration-tolerance", type=float, default=2.0)
    p.add_argument(
        "--no-key-match",
        dest="key_must_match",
        action="store_false",
        help="Do not require Rekordbox key to match in the prefilter.",
    )
    p.add_argument("--fingerprint-threshold", type=float, default=0.85)
    p.add_argument(
        "--skip-fingerprint",
        action="store_true",
        help="Skip the fingerprint stage; report on metadata prefilter alone.",
    )
    p.add_argument("--fpcalc-path", help="Path to fpcalc binary if not on PATH.")
    p.set_defaults(handler=_run)
    return p


def _run(args: argparse.Namespace) -> int:
    from sdm.features.rekordbox.command import run

    return run(args)
