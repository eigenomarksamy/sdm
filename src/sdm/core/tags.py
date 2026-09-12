"""Reading metadata out of audio files.

Two readers, because the callers need different things:

- `read_basic_tags` (eyed3) returns just title/artist and reports failures to
  the caller. The catalog uses it — it wants an error list it can print.
- `tracks_from_files` (mutagen) returns full `Track` objects including BPM, key
  and duration, across ID3 and Vorbis containers. The Rekordbox feature uses it
  as its last-resort source when no database is readable.

Both are best-effort by design: a file with unreadable tags yields "Unknown"
rather than aborting the run.
"""
from __future__ import annotations

from typing import Optional

from sdm.core.track import Track


def read_basic_tags(filepath: str) -> tuple[str, str, Optional[str]]:
    """Return `(title, artist, error)` for one file, via eyed3.

    Missing tags become "Unknown". `error` is a message string if the file
    could not be parsed at all, otherwise None.
    """
    import eyed3

    title = "Unknown"
    artist = "Unknown"

    try:
        audiofile = eyed3.load(filepath)

        if audiofile and audiofile.tag:
            title = audiofile.tag.title or "Unknown"
            artist = audiofile.tag.artist or "Unknown"

    except Exception as e:
        return title, artist, str(e)

    return title, artist, None


def _first(value):
    """Unwrap a tag value to a scalar.

    Vorbis comments are multi-valued, so mutagen hands back a `list` for FLAC and
    OGG; ID3 hands back a frame object that stringifies to its text. Taking
    `[0]` only for the list case is what keeps a FLAC title from arriving as the
    literal string `"['Somefunkydrum']"`.
    """
    if isinstance(value, list):
        return value[0] if value else None
    return value


def _tag(tags, *names):
    """First non-empty value among `names`, or None.

    The names are tried across container conventions on purpose — `TIT2` is ID3,
    `title` is Vorbis, `©nam` is MP4 — because *sniffing the container does not
    work*: every one of mutagen's tag objects has `.get`, so a previous version
    of this function that branched on `hasattr(tags, "get")` sent FLAC down the
    ID3 path, where `TBPM`/`TKEY` do not exist and the Vorbis lookups below were
    unreachable. Every FLAC in a library therefore came out with no BPM, no key,
    and a list-shaped title. Looking up all the spellings has no such failure
    mode: the names do not collide across formats, so the first hit is right.
    """
    for name in names:
        value = _first(tags.get(name))
        if value is not None and str(value) != "":
            return value
    return None


def tracks_from_files(files: list[str], *, start_idx: int = 0) -> list[Track]:
    """Build `Track` objects for the given audio files from their embedded tags.

    Files whose duration cannot be determined are skipped, since duration is
    what the duplicate prefilter keys on. Ids are sequential from `start_idx`,
    so callers merging several sources pass the running count.
    """
    try:
        from mutagen import File
    except ImportError:
        raise RuntimeError("mutagen is required for ID3 reading. Install with: pip install mutagen")

    tracks: list[Track] = []
    idx = start_idx
    for filepath in files:
        idx += 1
        title = "Unknown"
        artist = "Unknown"
        bpm = None
        duration = None
        key = None

        try:
            audio = File(filepath)
            if audio is None:
                continue

            # Get duration
            if hasattr(audio, "info") and hasattr(audio.info, "length"):
                duration = audio.info.length

            # Get title, artist, BPM, key from tags. One lookup per field across
            # every container's spelling of it — see `_tag`.
            if hasattr(audio, "tags") and audio.tags:
                tags = audio.tags

                title = _tag(tags, "TIT2", "title", "\xa9nam") or "Unknown"
                artist = _tag(tags, "TPE1", "artist", "\xa9ART") or "Unknown"

                if isinstance(title, bytes):
                    title = title.decode("utf-8", errors="replace")
                if isinstance(artist, bytes):
                    artist = artist.decode("utf-8", errors="replace")

                bpm_tag = _tag(tags, "TBPM", "bpm", "tmpo")
                if bpm_tag is not None:
                    try:
                        bpm = float(str(bpm_tag))
                    except (ValueError, TypeError):
                        pass
                    # A "0" BPM tag is a placeholder, not a measurement. Leaving
                    # it as 0.0 would make `require_bpm` count the track as
                    # analyzed and then compare it against nothing.
                    if bpm is not None and bpm <= 0:
                        bpm = None

                key_tag = _tag(tags, "TKEY", "initialkey", "key")
                if key_tag is not None:
                    key = str(key_tag) or None
        except Exception:
            pass

        if duration is None:
            continue

        tracks.append(
            Track(
                id=str(idx),
                title=str(title),
                artist=str(artist),
                file_path=filepath,
                bpm=bpm,
                key=key,
                duration_seconds=duration,
            )
        )
    return tracks
