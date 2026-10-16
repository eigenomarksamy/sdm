"""`sdm playlist-export` — write a Spotify playlist to CSV.

Read-only against Spotify, like `playlist-diff`: read-only scopes, and the CSV
is the only thing written. The same limit applies too, because it is the same
API: only playlists the user owns or collaborates on (see `sdm.core.spotify`).

The export doubles as `playlist-diff`'s offline copy. The login is not saved
between runs, so export once and diff the CSV as often as needed with no login
— which holds because `sdm.core.playlist` defines the CSV's writer and reader
side by side.
"""
from __future__ import annotations

import argparse


def add_parser(subparsers, parents=()) -> argparse.ArgumentParser:
    p = subparsers.add_parser(
        "playlist-export",
        parents=list(parents),
        help="Export a Spotify playlist you own or collaborate on to CSV.",
        description="Read a Spotify playlist through the Spotify API and write "
                    "every track to CSV, with Exportify's column names. Only "
                    "playlists you own or collaborate on - a Spotify limit "
                    "since February 2026. The CSV can be passed straight to "
                    "`sdm playlist-diff`.",
    )
    p.add_argument("playlist",
                   help="A Spotify playlist link, spotify:playlist: URI or ID.")
    p.add_argument("--output-csv", default=None,
                   help="Destination CSV (default: "
                        "<out-dir>/playlist-export/<playlist name>.csv). A bare "
                        "filename lands in that directory; a path with a "
                        "directory component is used as given.")
    p.add_argument("--client-id", default=None,
                   help="Client ID of your Spotify developer app (default: "
                        "$SDM_SPOTIFY_CLIENT_ID).")
    p.add_argument("--no-browser", action="store_true",
                   help="Print the Spotify login URL instead of opening a browser.")
    p.set_defaults(handler=_run)
    return p


def _run(args: argparse.Namespace) -> int:
    from sdm.features.playlist_export.command import run

    return run(args)
