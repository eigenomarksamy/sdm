"""Opening a Rekordbox `master.db` and reading its rows, for any feature.

Two features read the database, for different things: `rekordbox` turns rows
into `Track`s for duplicate detection, and `quality` reads what Rekordbox
recorded about each *file* — bitrate, sample rate, bit depth — to diff against
what the audio measures. Rule 1 puts what they share here: opening the database
(an explicit `master.db`, or the local install's, which pyrekordbox locates)
and walking its content rows. What each feature makes of a row stays in the
feature; `RekordboxFile` is this module's own conversion, kept plain so
`quality` never sees a pyrekordbox ORM object.

Read-only, like everything that opens the database: pyrekordbox is only ever
asked to query.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Iterator, Optional


@dataclass(frozen=True)
class RekordboxFile:
    """What Rekordbox's database says about one audio file.

    These are Rekordbox's *claims*, read when it imported the file, and they can
    be wrong: 54 rows of the reference library record a VBR mp3 averaging
    ~130 kbps as 32 kbps. Zero means "not recorded" in these columns and is
    read as None.
    """
    file_path: str                    # as the database stores it, normalized
    file_size: Optional[int]
    file_type: Optional[str]          # "mp3", "flac", ...; "type 25" for a code pyrekordbox does not name
    bitrate_kbps: Optional[int]
    sample_rate: Optional[int]
    bit_depth: Optional[int]
    duration_seconds: Optional[int]   # whole seconds: Rekordbox stores no fraction


def open_database(db_path: Optional[str] = None):
    """A pyrekordbox `Rekordbox6Database` for `db_path`, or the local install's."""
    from pyrekordbox import Rekordbox6Database

    return Rekordbox6Database(path=db_path) if db_path else Rekordbox6Database()


def iter_content(db) -> Iterator:
    """Every content (track) row, across the pyrekordbox API spellings seen so far."""
    if hasattr(db, "get_content"):
        return iter(db.get_content())
    if hasattr(db, "djmd_content"):
        return iter(db.djmd_content)
    raise RuntimeError("Unrecognized pyrekordbox v6 API.")


def load_files(db_path: Optional[str] = None) -> list[RekordboxFile]:
    """One `RekordboxFile` per content row that names a file.

    Rows without a `FolderPath` are skipped: they are streaming entries, with
    no file on disk to compare anything against.
    """
    try:
        from pyrekordbox.db6.tables import FileType
    except ImportError:  # an older pyrekordbox: codes are reported as numbers
        FileType = None

    files: list[RekordboxFile] = []
    for row in iter_content(open_database(db_path)):
        folder = getattr(row, "FolderPath", None) or ""
        if not folder:
            continue
        files.append(
            RekordboxFile(
                file_path=os.path.normpath(folder),
                file_size=_positive(getattr(row, "FileSize", None)),
                file_type=_file_type(getattr(row, "FileType", None), FileType),
                bitrate_kbps=_positive(getattr(row, "BitRate", None)),
                sample_rate=_positive(getattr(row, "SampleRate", None)),
                bit_depth=_positive(getattr(row, "BitDepth", None)),
                duration_seconds=_positive(getattr(row, "Length", None)),
            )
        )
    return files


def _positive(value) -> Optional[int]:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _file_type(code, enum) -> Optional[str]:
    if code is None:
        return None
    if enum is not None:
        try:
            return enum(code).name.lower()
        except ValueError:
            pass
    return f"type {code}"
