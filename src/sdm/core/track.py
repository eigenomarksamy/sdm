"""The one track model shared across features.

Deliberately flat and dependency-free: readers convert whatever they parsed
(Rekordbox ORM rows, ID3 tags, filesystem walks) into this before anything
downstream sees it, so no other module depends on pyrekordbox or mutagen types.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

#: Audio extensions recognized when walking a library directory.
AUDIO_EXTS = (".mp3", ".m4a", ".flac", ".aif", ".aiff", ".wav", ".ogg")


@dataclass(frozen=True)
class Track:
    id: str
    title: str
    artist: str
    file_path: str          # absolute path on the local filesystem
    bpm: Optional[float]    # beats per minute (None if Rekordbox has no value)
    key: Optional[str]      # Rekordbox key label, e.g. "8A", "C minor"
    duration_seconds: Optional[float]
