"""`sdm playlist-diff` — which tracks of a Spotify playlist a folder does not have.

Read-only on both sides: it reads the playlist and the folder's tags, and
writes only its reports. The Spotify token it asks for has read-only scopes, so
it could not modify a playlist even by mistake.

The first registered feature to need the network and a credential. See
`spotify_api.py` for why the API only covers playlists the user owns or
collaborates on, and `sources.py` for the CSV route that covers the rest.
"""
from __future__ import annotations

import argparse


def add_parser(subparsers, parents=()) -> argparse.ArgumentParser:
    p = subparsers.add_parser(
        "playlist-diff",
        parents=list(parents),
        help="List the tracks of a Spotify playlist that a music folder does not have.",
        description="Read a Spotify playlist - through the Spotify API for a "
                    "playlist you own or collaborate on, or from a CSV export "
                    "of any playlist - match its tracks against a music folder "
                    "by title and artist, and report the ones the folder is "
                    "missing. Read-only: touches neither the playlist nor the "
                    "files.",
    )
    p.add_argument("playlist",
                   help="A Spotify playlist link, spotify:playlist: URI or ID, "
                        "or the path to a CSV export of a playlist (Exportify, "
                        "TuneMyMusic and similar tools).")
    p.add_argument("directory",
                   help="Music folder to compare against, searched recursively.")
    p.add_argument("--output-dir", default=None,
                   help="Write reports here instead of <out-dir>/playlist-diff/.")
    p.add_argument("--client-id", default=None,
                   help="Client ID of your Spotify developer app (default: "
                        "$SDM_SPOTIFY_CLIENT_ID). Only needed for a link; a CSV "
                        "needs no account.")
    p.add_argument("--no-browser", action="store_true",
                   help="Print the Spotify login URL instead of opening a browser.")
    p.set_defaults(handler=_run)
    return p


def _run(args: argparse.Namespace) -> int:
    from sdm.features.playlist_diff.command import run

    return run(args)
