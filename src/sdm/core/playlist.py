"""Where a playlist's track list comes from: a Spotify link, or a CSV export.

Both produce the same `Playlist`, so nothing downstream knows which it was.
The CSV route exists because the API cannot read most playlists: since
Spotify's February 2026 changes, playlist contents are only returned for
playlists the logged-in user owns or collaborates on (see `spotify_api`). A CSV
exported by a tool that has broader access — Exportify, TuneMyMusic, Soundiiz —
covers the rest, and needs no account here at all.

Column names differ between those tools and none of them publishes a spec, so
`read_csv` finds columns by name, case-insensitively, from a list of aliases,
and insists only on a title and an artist column.

Stdlib only: this is imported by the handler, but nothing here needs more.
"""
from __future__ import annotations

import csv
import os
import re
from dataclasses import dataclass, field
from typing import Optional

_SPOTIFY_ID = r"[A-Za-z0-9]{22}"
# `(?:[\w-]+/)*` admits the locale and embed prefixes Spotify puts in share
# links: open.spotify.com/intl-de/playlist/..., open.spotify.com/embed/playlist/...
_PLAYLIST_URL = re.compile(rf"open\.spotify\.com/(?:[\w-]+/)*playlist/({_SPOTIFY_ID})")
_PLAYLIST_URI = re.compile(rf"spotify:(?:user:[^:]+:)?playlist:({_SPOTIFY_ID})")
_TRACK_URI = re.compile(rf"spotify:track:({_SPOTIFY_ID})")

#: Header aliases per field, most specific first. Matched after `_header_key`.
CSV_COLUMNS = {
    "title": ("track name", "title", "song name", "song", "name", "track"),
    "artist": ("artist name(s)", "artist name", "artist names", "artists", "artist"),
    "album": ("album name", "album"),
    # Only columns that say they are milliseconds. A bare "duration" could be
    # seconds or m:ss depending on the tool, and a wrong unit is worse than none.
    "duration_ms": ("track duration (ms)", "duration (ms)", "duration_ms"),
    "isrc": ("isrc",),
    "url": ("track uri", "spotify - id", "spotify id", "spotify url", "spotify uri", "uri", "url"),
    "playlist": ("playlist name", "playlist"),
}


class PlaylistSourceError(ValueError):
    """The playlist argument is not usable: not a playlist link, or a CSV without the columns needed."""


@dataclass(frozen=True)
class PlaylistTrack:
    title: str
    artists: tuple[str, ...]
    album: str = ""
    duration_ms: Optional[int] = None
    isrc: str = ""
    url: str = ""
    #: A file from the user's own computer added to the playlist in the Spotify
    #: app. It has a name but no Spotify ID, and is matched like any other.
    is_local: bool = False


@dataclass
class Playlist:
    name: str
    owner: str
    tracks: list[PlaylistTrack] = field(default_factory=list)
    #: Entries with no track to compare: podcast episodes, and tracks Spotify
    #: has removed (the API returns them with a null item).
    skipped: int = 0


def parse_playlist_ref(value: str) -> Optional[str]:
    """Return the playlist ID from a share link, `spotify:playlist:` URI or bare ID, else None."""
    value = value.strip()
    match = _PLAYLIST_URL.search(value) or _PLAYLIST_URI.fullmatch(value)
    if match:
        return match.group(1)
    if re.fullmatch(_SPOTIFY_ID, value):
        return value
    return None


def _track_url(value: str) -> str:
    """A track reference as a clickable link where it can be: URI and bare ID both become one."""
    value = value.strip()
    match = _TRACK_URI.fullmatch(value)
    if match:
        return f"https://open.spotify.com/track/{match.group(1)}"
    if re.fullmatch(_SPOTIFY_ID, value):
        return f"https://open.spotify.com/track/{value}"
    return value


def _header_key(name: str) -> str:
    """Fold a CSV header for alias lookup. TuneMyMusic writes "Spotify – id" with an en dash."""
    name = name.replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", " ", name).strip().casefold()


def _split_artists(value: str) -> tuple[str, ...]:
    r"""Split a CSV artist cell on commas and semicolons, honouring `\,` escapes."""
    parts = re.split(r"(?<!\\)[,;]", value)
    return tuple(p.replace("\\,", ",").strip() for p in parts if p.strip())


def _int_or_none(value: str) -> Optional[int]:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def read_csv(path: str) -> Playlist:
    """Read a playlist exported to CSV. Raises `PlaylistSourceError` if it has no title/artist columns."""
    # utf-8-sig: Excel-friendly exports start with a byte-order mark, which
    # would otherwise become part of the first header's name.
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        headers = {_header_key(h): h for h in reader.fieldnames or () if h}

        columns: dict[str, str] = {}
        for name, aliases in CSV_COLUMNS.items():
            for alias in aliases:
                if alias in headers:
                    columns[name] = headers[alias]
                    break

        missing = [name for name in ("title", "artist") if name not in columns]
        if missing:
            raise PlaylistSourceError(
                f"{path}: no {' or '.join(missing)} column. Found: "
                f"{', '.join(reader.fieldnames or []) or 'no header row'}"
            )

        def cell(row: dict, name: str) -> str:
            column = columns.get(name)
            return (row.get(column) or "").strip() if column else ""

        playlist = Playlist(name="", owner="")
        for row in reader:
            title = cell(row, "title")
            if not title:
                playlist.skipped += 1
                continue
            playlist.name = playlist.name or cell(row, "playlist")
            playlist.tracks.append(PlaylistTrack(
                title=title,
                artists=_split_artists(cell(row, "artist")),
                album=cell(row, "album"),
                duration_ms=_int_or_none(cell(row, "duration_ms")),
                isrc=cell(row, "isrc"),
                url=_track_url(cell(row, "url")),
            ))

    playlist.name = playlist.name or os.path.splitext(os.path.basename(path))[0]
    return playlist
