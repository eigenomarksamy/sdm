"""Runs the `sdm playlist-export` subcommand.

Log in -> read the playlist -> write the CSV. Everything that knows Spotify or
the CSV format is in core (`sdm.core.spotify`, `sdm.core.playlist`), shared
with `playlist-diff`; what this module owns is the messages, and the default
destination.
"""
from __future__ import annotations

import argparse
import os
import sys

from sdm.core.paths import resolve_output
from sdm.core.playlist import parse_playlist_ref, playlist_slug, write_playlist_csv
from sdm.core.spotify import (
    CLIENT_ID_ENV,
    PlaylistNotAccessible,
    SpotifyError,
    fetch_playlist,
    login,
    resolve_client_id,
)


def run(args: argparse.Namespace) -> int:
    playlist_id = parse_playlist_ref(args.playlist)
    if playlist_id is None:
        hint = ""
        if os.path.isfile(args.playlist):
            hint = " (that is a file: to compare a CSV with a folder, use `sdm playlist-diff`)"
        print(f"error: not a Spotify playlist link, URI or ID: {args.playlist}{hint}",
              file=sys.stderr)
        return 2

    client_id = resolve_client_id(args.client_id)
    if not client_id:
        print(
            f"error: exporting a playlist needs a Spotify app client ID. Set "
            f"{CLIENT_ID_ENV} or pass --client-id; the one-time setup is in the "
            "README under \"Spotify access\".",
            file=sys.stderr,
        )
        return 2

    try:
        token = login(client_id, open_browser=not args.no_browser, log=print)
        playlist = fetch_playlist(playlist_id, token, log=print)
    except PlaylistNotAccessible as exc:
        print(
            f"error: {exc} To export it, copy its tracks into a playlist of your "
            "own in the Spotify app (select all, Add to playlist) and export that.",
            file=sys.stderr,
        )
        return 1
    except SpotifyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    output_csv = resolve_output(args.output_csv, "playlist-export",
                                f"{playlist_slug(playlist.name)}.csv")
    write_playlist_csv(output_csv, playlist)

    owner = f" by {playlist.owner}" if playlist.owner else ""
    skipped = (f"; {playlist.skipped} skipped (podcast episodes or tracks no longer on Spotify)"
               if playlist.skipped else "")
    print(f"exported {len(playlist.tracks)} track(s) from '{playlist.name}'{owner}{skipped}")
    print(f"wrote {output_csv}")
    print(f"compare it with a folder, no login needed: sdm playlist-diff \"{output_csv}\" <folder>")
    return 0
