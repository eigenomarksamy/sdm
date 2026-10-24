"""Runs the `sdm playlist-diff` subcommand.

Load the playlist (API or CSV) -> read the folder's tags -> match, checking
each file that matches by name (`checks.py`) -> report. The two reports are
the answer and its evidence: `missing_<playlist>.csv` is what to go and get
(and the files to replace, as `mismatch`), and `matched_<playlist>.csv` names
the file each "owned" track was matched to, with both lengths, so a wrong
match can be caught rather than trusted.
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import Optional

from sdm.core.paths import out_dir
from sdm.core.playlist import (
    Playlist,
    PlaylistSourceError,
    PlaylistTrack,
    parse_playlist_ref,
    playlist_slug,
    read_playlist_csv,
)
from sdm.core.report import ensure_dir, write_csv
from sdm.core.spotify import (
    CLIENT_ID_ENV,
    PlaylistNotAccessible,
    SpotifyError,
    fetch_playlist,
    login,
    resolve_client_id,
)
from sdm.core.tags import read_title_artist_raw
from sdm.core.track import iter_audio_files
from sdm.features.playlist_diff.checks import FileFacts, clock, inspect, verdict
from sdm.features.playlist_diff.matching import LocalIndex, LocalTrack, Match, Vet


def run(args: argparse.Namespace) -> int:
    directory = args.directory
    if not os.path.isdir(directory):
        print(f"error: not a directory: {directory}", file=sys.stderr)
        return 2

    try:
        playlist = _load_playlist(args)
    except PlaylistSourceError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except PlaylistNotAccessible as exc:
        # `sdm playlist-export` is no way round this: it reads the same API.
        print(
            f"error: {exc} Export it to CSV with a tool that can still read it "
            "(Exportify, TuneMyMusic) and pass the file instead, or copy its "
            "tracks into a playlist of your own.",
            file=sys.stderr,
        )
        return 1
    except SpotifyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if playlist is None:
        return 2

    owner = f" by {playlist.owner}" if playlist.owner else ""
    print(f"playlist '{playlist.name}'{owner}: {len(playlist.tracks)} track(s)")

    files = sorted(iter_audio_files(directory))
    print(f"reading tags of {len(files)} audio file(s) in {directory}")
    index = LocalIndex(
        LocalTrack(path, *read_title_artist_raw(path)[:2]) for path in files
    )

    facts: dict[str, FileFacts] = {}

    def file_facts(path: str) -> FileFacts:
        # A file can be a candidate for several playlist tracks; read it once.
        if path not in facts:
            facts[path] = inspect(path)
        return facts[path]

    def vet_for(track: PlaylistTrack) -> Vet:
        return lambda local: verdict(file_facts(local.path), track.duration_ms)

    results = [(track, index.match(track.title, track.artists, vet_for(track)))
               for track in playlist.tracks]
    absent = [(t, m) for t, m in results if m.status != "owned"]
    owned = [(t, m) for t, m in results if m.status == "owned"]

    for track, match in absent:
        print(f"{match.status:<8} {_name(track)}")
        if match.note:
            print(f"{'':<8} {match.note}")

    maybe = sum(1 for _, m in absent if m.status == "maybe")
    mismatch = sum(1 for _, m in absent if m.status == "mismatch")
    print(
        f"{len(results)} track(s): {len(owned)} in the folder, "
        f"{len(absent) - maybe - mismatch} missing, {maybe} maybe (a different "
        f"version, or a file with no artist tag), {mismatch} mismatch (a file "
        f"by that name that is not the track: far too long or short, cut off, "
        f"or unreadable)"
        + (f"; {playlist.skipped} skipped (episodes or unavailable)" if playlist.skipped else "")
    )

    def local_duration(match: Match) -> str:
        return clock(file_facts(match.local.path).duration_seconds) if match.local else ""

    report_dir = ensure_dir(args.output_dir) if args.output_dir else out_dir("playlist-diff")
    slug = playlist_slug(playlist.name)
    missing_path = os.path.join(report_dir, f"missing_{slug}.csv")
    matched_path = os.path.join(report_dir, f"matched_{slug}.csv")

    write_csv(
        missing_path,
        ["#", "status", "artist", "title", "album", "duration", "isrc",
         "spotify_url", "closest_local_file", "local_duration", "note"],
        (
            [i, m.status, ", ".join(t.artists), t.title, t.album,
             _duration(t.duration_ms), t.isrc, t.url,
             m.local.path if m.local else "", local_duration(m), m.note]
            for i, (t, m) in enumerate(absent, start=1)
        ),
    )
    write_csv(
        matched_path,
        ["#", "artist", "title", "duration", "local_file", "local_duration", "matched_via"],
        (
            [i, ", ".join(t.artists), t.title, _duration(t.duration_ms),
             m.local.path, local_duration(m), m.via]
            for i, (t, m) in enumerate(owned, start=1)
        ),
    )
    print(f"wrote {missing_path}")
    print(f"wrote {matched_path}")
    return 0


def _load_playlist(args: argparse.Namespace) -> Optional[Playlist]:
    """The playlist from a CSV path or a Spotify reference. None after printing a usage error."""
    source = args.playlist
    if os.path.isfile(source):
        return read_playlist_csv(source)

    playlist_id = parse_playlist_ref(source)
    if playlist_id is None:
        raise PlaylistSourceError(
            f"not a Spotify playlist link or an existing CSV file: {source}"
        )

    client_id = resolve_client_id(args.client_id)
    if not client_id:
        print(
            f"error: reading a playlist link needs a Spotify app client ID. Set "
            f"{CLIENT_ID_ENV} or pass --client-id; the one-time setup is in the "
            "README under \"Spotify access\". Or pass a CSV export of the "
            "playlist, which needs no account.",
            file=sys.stderr,
        )
        return None

    token = login(client_id, open_browser=not args.no_browser, log=print)
    return fetch_playlist(playlist_id, token, log=print)


def _name(track: PlaylistTrack) -> str:
    return f"{', '.join(track.artists)} - {track.title}" if track.artists else track.title


def _duration(ms: Optional[int]) -> str:
    if not ms:
        return ""
    seconds = round(ms / 1000)
    return f"{seconds // 60}:{seconds % 60:02d}"
