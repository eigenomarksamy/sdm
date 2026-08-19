"""`sdm download` — fetch tracks and playlists from Spotify."""
from __future__ import annotations

import argparse
import os


def add_parser(subparsers, parents=()) -> argparse.ArgumentParser:
    p = subparsers.add_parser(
        "download",
        parents=list(parents),
        help="Download tracks or playlists from Spotify.",
        description="Download tracks from Spotify, tagged and with cover art.",
    )
    p.add_argument("--link", "-l", nargs="+", dest="link",
                   help="URL of the spotify track or playlist.")
    # Downloaded audio is the product, not a report, so it stays where the user
    # points it and is not routed through --out-dir.
    p.add_argument("--output", "-o", nargs="?",
                   default=os.path.join(os.getcwd(), "downloads"),
                   help="Path to save the downloaded track(s).")
    p.add_argument("--sync", "-s", nargs="?", const="sync.json",
                   help="Path of sync.json file to sync local playlists "
                        "folders with Spotify playlists.")
    p.add_argument("--folder", nargs="?", default=True,
                   help="Create a folder for the playlist "
                        "(default: True).")
    p.add_argument("--no-make-dirs", action="store_true",
                   dest="no_make_dirs",
                   help="Disable creation of missing folders in download directory "
                        "(default: False).")
    p.add_argument("--tf", action="store_true", dest="track_name_convention",
                   help="Select naming convention (default: Artist - Track).")
    p.add_argument("--disable-log", action="store_true", dest="disable_log",
                   help="Disable logging (default: False).")
    p.add_argument("--quiet", "-q", action="store_true", dest="quiet",
                   help="Run quietly (default: False).")
    p.add_argument("--dry-run", "-n", action="store_true", dest="dry_run",
                   help="Simulate a run (default: False).")
    p.add_argument("--disable-gui", action="store_true", dest="disable_gui",
                   help="Disable GUI (default: False).")
    p.add_argument("--pre-order", action="store_true", dest="pre_order",
                   help="Preserve order (default: False).")
    p.add_argument("--run-pp", action="store_true", dest="run_pp",
                   help="Run post-processing (default: False).")
    p.set_defaults(handler=_run)
    return p


def _run(args: argparse.Namespace):
    from sdm.features.spotify.command import run

    return run(args)
