"""Read tracks from a Rekordbox library.

Source resolution order:
  1. A master.db given directly (--db-path) or sitting on the USB.
  2. The local Rekordbox master.db (pyrekordbox auto-locates it). This is the
     only source that carries the analyzed BPM and key, so it is preferred even
     when a USB is supplied. With --usb-path we then restrict the result to the
     tracks actually on the USB (matched by filename) and merge in any USB files
     missing from the local DB via their ID3 tags.
  3. ID3 tags from the USB's Contents/ folder (last resort; no analyzed BPM/key).

The exported USB databases (export.pdb / exportLibrary.db) are DeviceSQL/
encrypted and are not readable by the installed pyrekordbox, so they are skipped.

Returns plain `Track` dataclasses so the rest of the pipeline doesn't depend on
pyrekordbox's ORM objects.
"""
from __future__ import annotations

import os
from typing import Iterator, Optional

from sdm.core.tags import tracks_from_files
from sdm.core.track import AUDIO_EXTS as _AUDIO_EXTS, Track, iter_audio_files


def resolve_db_path(usb_path: Optional[str], db_path: Optional[str]) -> str:
    if db_path:
        return db_path
    if not usb_path:
        raise ValueError("Either --usb-path or --db-path must be provided.")
    return os.path.normpath(os.path.join(usb_path, "PIONEER", "rekordbox", "master.db"))


def load_tracks(db_path: str, *, usb_path: Optional[str] = None) -> list[Track]:
    """Open the Rekordbox library and return all content rows as Track objects.

    See the module docstring for the source resolution order.
    """
    db_path = os.path.normpath(db_path)
    usb_root = usb_path or os.path.dirname(os.path.dirname(db_path))
    contents_dir = os.path.normpath(os.path.join(usb_root, "Contents"))

    # 1. A master.db we can open directly (explicit --db-path or one on the USB).
    if db_path.endswith("master.db") and os.path.isfile(db_path):
        try:
            return _load_v6_tracks(db_path, usb_path)
        except Exception as e:
            print(f"master.db at {db_path} failed to load: {e}")

    # 2. The local Rekordbox master.db — the only source with analyzed BPM/key.
    try:
        local_tracks = _load_local_master_db()
    except Exception as e:
        print(f"local Rekordbox master.db unavailable: {e}")
    else:
        if usb_path and os.path.isdir(contents_dir):
            print(f"using local Rekordbox analysis, scoped to USB at {contents_dir}")
            return _scope_to_usb(local_tracks, contents_dir)
        print("using local Rekordbox master.db (full library)")
        return local_tracks

    # 3. Last resort: ID3 tags from the USB (no analyzed BPM/key available).
    if os.path.isdir(contents_dir):
        print(f"falling back to ID3 tags from {contents_dir} (BPM/key will be sparse)")
        return _load_id3_tracks(contents_dir, usb_root)

    raise FileNotFoundError(
        f"Could not find a Rekordbox database or Contents folder. "
        f"Tried: {db_path}, local master.db, {contents_dir}"
    )


def _load_v6_tracks(db_path: str, usb_path: Optional[str]) -> list[Track]:
    if not os.path.isfile(db_path):
        raise FileNotFoundError(f"master.db not found at {db_path}")

    from pyrekordbox import Rekordbox6Database

    db = Rekordbox6Database(path=db_path)
    tracks: list[Track] = []
    for row in _iter_content_v6(db):
        file_path = _resolve_file_path(row, usb_path=usb_path)
        if not file_path:
            continue
        tracks.append(
            Track(
                id=str(_get(row, "ID")),
                title=_get(row, "Title") or "",
                artist=_artist_name_v6(row),
                file_path=file_path,
                bpm=_bpm_v6(row),
                key=_key_name_v6(row),
                duration_seconds=_duration_v6(row),
            )
        )
    return tracks


def _load_local_master_db() -> list[Track]:
    """Load every track from the local Rekordbox master.db (auto-located)."""
    from pyrekordbox import Rekordbox6Database

    db = Rekordbox6Database()
    tracks: list[Track] = []
    for row in _iter_content_v6(db):
        folder = _get(row, "FolderPath") or ""
        if not folder:
            continue
        tracks.append(
            Track(
                id=str(_get(row, "ID")),
                title=_get(row, "Title") or "",
                artist=_artist_name_v6(row),
                file_path=os.path.normpath(folder),
                bpm=_bpm_v6(row),
                key=_key_name_v6(row),
                duration_seconds=_duration_v6(row),
            )
        )
    return tracks


def _scope_to_usb(local_tracks: list[Track], contents_dir: str) -> list[Track]:
    """Restrict local-DB tracks to those present on the USB.

    Matches USB audio files to local tracks by filename. Matched tracks keep the
    local analysis (BPM/key) but point at the USB copy. USB files with no local
    match are read from their ID3 tags so they aren't dropped (BPM/key blank).
    """
    by_name: dict[str, Track] = {}
    for t in local_tracks:
        by_name.setdefault(os.path.basename(t.file_path).lower(), t)

    tracks: list[Track] = []
    matched = 0
    unmatched_files: list[str] = []
    for root, _, files in os.walk(contents_dir):
        for filename in files:
            if not filename.lower().endswith(_AUDIO_EXTS):
                continue
            usb_file = os.path.normpath(os.path.join(root, filename))
            local = by_name.get(filename.lower())
            if local is not None:
                matched += 1
                tracks.append(
                    Track(
                        id=local.id,
                        title=local.title,
                        artist=local.artist,
                        file_path=usb_file,
                        bpm=local.bpm,
                        key=local.key,
                        duration_seconds=local.duration_seconds,
                    )
                )
            else:
                unmatched_files.append(usb_file)

    if unmatched_files:
        tracks.extend(tracks_from_files(unmatched_files, start_idx=len(tracks)))
    print(f"matched {matched} USB track(s) to local analysis, {len(unmatched_files)} via ID3 only")
    return tracks


def _load_id3_tracks(contents_dir: str, usb_root: str) -> list[Track]:
    """Walk Contents/ and read ID3 tags + duration from audio files."""
    return tracks_from_files(list(iter_audio_files(contents_dir)), start_idx=0)


def _iter_content_v6(db) -> Iterator:
    if hasattr(db, "get_content"):
        return iter(db.get_content())
    if hasattr(db, "djmd_content"):
        return iter(db.djmd_content)
    raise RuntimeError("Unrecognized pyrekordbox v6 API.")


def _get(row, attr: str, default=None):
    return getattr(row, attr, default)


def _artist_name_v6(row) -> str:
    artist = _get(row, "Artist")
    if artist is None:
        return ""
    name = getattr(artist, "Name", None)
    return name or str(artist) or ""


def _key_name_v6(row) -> Optional[str]:
    key = _get(row, "Key")
    if key is None:
        return None
    name = getattr(key, "ScaleName", None) or getattr(key, "Name", None)
    return name or None


def _bpm_v6(row) -> Optional[float]:
    raw = _get(row, "BPM")
    if raw is None:
        return None
    try:
        bpm = float(raw)
    except (TypeError, ValueError):
        return None
    return bpm / 100.0 if bpm > 1000 else bpm


def _duration_v6(row) -> Optional[float]:
    raw = _get(row, "Length")
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _resolve_file_path(row, *, usb_path: Optional[str]) -> Optional[str]:
    folder = _get(row, "FolderPath") or ""
    if not folder:
        return None
    if usb_path and folder.startswith("/"):
        return os.path.normpath(os.path.join(usb_path, folder.lstrip("/")))
    return folder

