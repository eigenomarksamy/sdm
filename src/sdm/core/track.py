"""The one track model shared across features.

Deliberately flat and dependency-free: readers convert whatever they parsed
(Rekordbox ORM rows, ID3 tags, filesystem walks) into this before anything
downstream sees it, so no other module depends on pyrekordbox or mutagen types.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Iterator, Optional

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


def iter_audio_files(directory: str) -> Iterator[str]:
    """Yield the normalized path of every file under `directory` in `AUDIO_EXTS`.

    Lives beside the extension list so the two never drift apart: every caller
    that walks a library sees the same set of files.

    AppleDouble stubs are skipped. A DJ USB that has been near a Mac carries a
    4KB `._Track.mp3` beside every `Track.mp3`; they match `AUDIO_EXTS` but hold
    resource-fork metadata, not audio, so every reader downstream would spend a
    tag parse or an `fpcalc` run on them only to throw the result away.
    """
    for root, _, filenames in os.walk(directory):
        for filename in filenames:
            if filename.startswith("._"):
                continue
            if filename.lower().endswith(AUDIO_EXTS):
                yield os.path.normpath(os.path.join(root, filename))
