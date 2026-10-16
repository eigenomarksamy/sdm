"""Spotify playlists as data: the model, link parsing, and the CSV format both ways.

Shared by `playlist-diff` (reads a playlist to compare against a folder) and
`playlist-export` (writes one to CSV). A `Playlist` comes either from the API
(`sdm.core.spotify`) or from a CSV file, and nothing downstream knows which.

**The CSV reader and writer live side by side on purpose.** An exported file has
to read back — `playlist-export` once, then `playlist-diff` against the CSV as
often as needed, with no login — and the only way to keep that true is to
define both halves of the format in one place.

Reading is lenient and writing is fixed. Exporters (Exportify, TuneMyMusic,
Soundiiz) disagree on header names and none publishes a spec, so
`read_playlist_csv` finds columns by alias, case-insensitively, and insists only
on a title and an artist column. `write_playlist_csv` uses Exportify's column
names, and every column the reader uses is spelled as one of its aliases.

Every track reference is held as a Spotify URI and turned into a link on
demand, so a URI, a bare ID or an open.spotify.com link in a CSV all land the
same way. Stdlib only.
"""
from __future__ import annotations

import csv
import os
import re
from dataclasses import dataclass, field
from typing import Callable, Optional

from sdm.core.report import write_csv

_SPOTIFY_ID = r"[A-Za-z0-9]{22}"
# `(?:[\w-]+/)*` admits the locale and embed prefixes Spotify puts in share
# links: open.spotify.com/intl-de/playlist/..., open.spotify.com/embed/playlist/...
_PLAYLIST_URL = re.compile(rf"open\.spotify\.com/(?:[\w-]+/)*playlist/({_SPOTIFY_ID})")
_PLAYLIST_URI = re.compile(rf"spotify:(?:user:[^:]+:)?playlist:({_SPOTIFY_ID})")
_TRACK_URL = re.compile(rf"open\.spotify\.com/(?:[\w-]+/)*track/({_SPOTIFY_ID})")
_TRACK_URI = re.compile(rf"spotify:track:({_SPOTIFY_ID})")

#: Header aliases the reader accepts per field, most specific first. Matched
#: after `_header_key`.
CSV_COLUMNS = {
    "title": ("track name", "title", "song name", "song", "name", "track"),
    "artist": ("artist name(s)", "artist name", "artist names", "artists", "artist"),
    "album": ("album name", "album"),
    # Only columns that say they are milliseconds. A bare "duration" could be
    # seconds or m:ss depending on the tool, and a wrong unit is worse than none.
    "duration_ms": ("track duration (ms)", "duration (ms)", "duration_ms"),
    "isrc": ("isrc",),
    "uri": ("track uri", "spotify - id", "spotify id", "spotify url", "spotify uri", "uri", "url"),
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
    #: `spotify:track:<id>`, `spotify:local:...` for a local file, "" if unknown.
    uri: str = ""
    #: A file from the user's own computer added to the playlist in the Spotify
    #: app. It has a name but no Spotify ID, and is matched like any other.
    is_local: bool = False
    # Filled from the API only, and written only by the export. A CSV read back
    # leaves them at their defaults: nothing that reads a CSV needs them.
    album_artists: tuple[str, ...] = ()
    release_date: str = ""
    disc_number: Optional[int] = None
    track_number: Optional[int] = None
    explicit: Optional[bool] = None
    added_at: str = ""
    added_by: str = ""

    @property
    def url(self) -> str:
        """The track's open.spotify.com link, or "" for a local file or an unknown track."""
        match = _TRACK_URI.fullmatch(self.uri)
        return f"https://open.spotify.com/track/{match.group(1)}" if match else ""


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


def playlist_slug(name: str) -> str:
    """A playlist name as a filename fragment. Unicode letters survive; NTFS takes them."""
    return re.sub(r"[^\w-]+", "_", name).strip("_")[:60] or "playlist"


def _track_uri(value: str) -> str:
    """Whatever a CSV holds for a track — URI, bare ID or link — as a URI, else ""."""
    value = value.strip()
    if value.startswith(("spotify:track:", "spotify:local:")):
        return value
    match = _TRACK_URL.search(value)
    if match:
        return f"spotify:track:{match.group(1)}"
    if re.fullmatch(_SPOTIFY_ID, value):
        return f"spotify:track:{value}"
    return ""


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


def read_playlist_csv(path: str) -> Playlist:
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
            uri = _track_uri(cell(row, "uri"))
            playlist.tracks.append(PlaylistTrack(
                title=title,
                artists=_split_artists(cell(row, "artist")),
                album=cell(row, "album"),
                duration_ms=_int_or_none(cell(row, "duration_ms")),
                isrc=cell(row, "isrc"),
                uri=uri,
                is_local=uri.startswith("spotify:local:"),
            ))

    playlist.name = playlist.name or os.path.splitext(os.path.basename(path))[0]
    return playlist


def _text(value) -> str:
    return "" if value is None else str(value)


#: What `write_playlist_csv` writes, in order. Exportify's column names, so the
#: file reads like one of its exports, plus "Playlist Name" so a CSV read back
#: keeps the playlist's real name rather than its filename. Artists are joined
#: with ", ": readable in a spreadsheet, and the reader splits on commas anyway.
EXPORT_COLUMNS: tuple[tuple[str, Callable[[PlaylistTrack], str]], ...] = (
    ("Track URI", lambda t: t.uri),
    ("Track Name", lambda t: t.title),
    ("Artist Name(s)", lambda t: ", ".join(t.artists)),
    ("Album Name", lambda t: t.album),
    ("Album Artist Name(s)", lambda t: ", ".join(t.album_artists)),
    ("Album Release Date", lambda t: t.release_date),
    ("Disc Number", lambda t: _text(t.disc_number)),
    ("Track Number", lambda t: _text(t.track_number)),
    ("Track Duration (ms)", lambda t: _text(t.duration_ms)),
    ("Explicit", lambda t: "" if t.explicit is None else str(t.explicit).lower()),
    ("ISRC", lambda t: t.isrc),
    ("Added By", lambda t: t.added_by),
    ("Added At", lambda t: t.added_at),
)


def write_playlist_csv(path: str, playlist: Playlist) -> None:
    """Write `playlist` as CSV, one row per track, in `EXPORT_COLUMNS` plus "Playlist Name".

    With a byte-order mark, unlike the reports: an export is a file to open,
    and Excel garbles every accented artist in UTF-8 without one. The reader
    strips it again (`utf-8-sig`), so the round trip is unaffected.
    """
    write_csv(
        path,
        [name for name, _ in EXPORT_COLUMNS] + ["Playlist Name"],
        ([get(track) for _, get in EXPORT_COLUMNS] + [playlist.name] for track in playlist.tracks),
        encoding="utf-8-sig",
    )
