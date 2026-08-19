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

            # Get title, artist, BPM, key from tags
            if hasattr(audio, "tags") and audio.tags:
                tags = audio.tags
                # ID3 (MP3)
                if hasattr(tags, "get"):
                    title = tags.get("TIT2") or tags.get("Title") or "Unknown"
                    artist = tags.get("TPE1") or tags.get("Artist") or "Unknown"
                    bpm_tag = tags.get("TBPM")
                    if bpm_tag and str(bpm_tag):
                        try:
                            bpm = float(str(bpm_tag))
                        except (ValueError, TypeError):
                            pass
                    key_tag = tags.get("TKEY")
                    if key_tag and str(key_tag):
                        key = str(key_tag)
                    if isinstance(title, bytes):
                        title = title.decode("utf-8", errors="replace")
                    if isinstance(artist, bytes):
                        artist = artist.decode("utf-8", errors="replace")
                # Vorbis (FLAC, OGG) and others
                else:
                    title = (tags.get("title") or ["Unknown"])[0] if isinstance(tags.get("title"), list) else tags.get("title") or "Unknown"
                    artist = (tags.get("artist") or ["Unknown"])[0] if isinstance(tags.get("artist"), list) else tags.get("artist") or "Unknown"
                    bpm_tag = tags.get("bpm")
                    if bpm_tag:
                        bpm_val = bpm_tag[0] if isinstance(bpm_tag, list) else bpm_tag
                        try:
                            bpm = float(bpm_val)
                        except (ValueError, TypeError):
                            pass
                    key_tag = tags.get("initialkey") or tags.get("key")
                    if key_tag:
                        key_val = key_tag[0] if isinstance(key_tag, list) else key_tag
                        key = str(key_val) or None
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
