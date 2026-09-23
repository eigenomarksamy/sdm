"""`sdm analyze` — read Rekordbox's own analysis off a Pioneer USB.

The other features ask what a library *contains*. This one asks what Rekordbox
*worked out* about it: the beat grid it computed and the phrase structure it
detected, both written beside every track under `PIONEER/USBANLZ/` and reachable
nowhere else — not in the tags, not in the exported database.

That makes it the one feature that needs no local Rekordbox install and no
`master.db`. A USB alone is enough, which is exactly the case `sdm rekordbox`
handles worst.

Read-only, like `sdm rekordbox`: it opens the USB's analysis files and writes
reports elsewhere. Nothing on the USB is touched.
"""
from __future__ import annotations

import argparse


def add_parser(subparsers, parents=()) -> argparse.ArgumentParser:
    p = subparsers.add_parser(
        "analyze",
        parents=list(parents),
        help="Read beat grids and phrase structure from a Pioneer USB.",
        description="Parse the Rekordbox analysis files on a Pioneer USB and "
                    "report each track's beat grid and phrase structure "
                    "(intro, verse, chorus, outro) to CSV and JSON. Needs no "
                    "Rekordbox install and no database — the USB carries it. "
                    "Read-only: nothing on the USB is written.",
    )
    p.add_argument("usb_path",
                   help="Mount path of the Rekordbox USB (e.g. D:/), or a "
                        "PIONEER/USBANLZ directory directly.")
    p.add_argument("--output-dir", default=None,
                   help="Write reports here instead of <out-dir>/analyze/.")
    p.add_argument("--limit", type=int, default=None, metavar="N",
                   help="Stop after N tracks. For sizing a run or sampling a "
                        "library before committing to the full scan.")
    p.add_argument("--export-beats", action="store_true",
                   help="Also write beats.csv, one row per beat of every grid. "
                        "The raw analysis, and large with it - a full library "
                        "runs to millions of rows.")
    p.set_defaults(handler=_run)
    return p


def _run(args: argparse.Namespace) -> int:
    from sdm.features.analyze.command import run

    return run(args)
