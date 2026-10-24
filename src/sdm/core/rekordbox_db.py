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
asked to query. Where sqlcipher3 is missing the query runs against a
decrypted copy (`open_database`), which is no less read-only for the original.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Callable, Iterator, Optional


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


@contextmanager
def open_database(db_path: Optional[str] = None, *, log: Optional[Callable[[str], None]] = None) -> Iterator:
    """A pyrekordbox `Rekordbox6Database` for `db_path`, or the local install's.

    Through sqlcipher3 when it is installed, which is what pyrekordbox does by
    default. Without it — it has no Pyodide build, so this is always the case
    in the browser build — `core.sqlcipher` decrypts the file into a plain
    copy under `tmp/`, pyrekordbox opens that with `unlock=False`, and the copy
    is deleted when the block exits. The rows are the same either way.
    """
    from pyrekordbox.db6.database import Rekordbox6Database

    if _have_sqlcipher():
        db = Rekordbox6Database(path=db_path) if db_path else Rekordbox6Database()
        try:
            yield db
        finally:
            db.close()
        return

    from pyrekordbox.db6.database import BLOB
    from pyrekordbox.utils import deobfuscate

    from sdm.core.paths import scratch
    from sdm.core.sqlcipher import decrypt_file

    source = db_path or _local_db_path()
    wal = source + "-wal"
    if log and os.path.isfile(wal) and os.path.getsize(wal):
        # Pages in the write-ahead log are not in the file this decrypts, and
        # decrypting them would break the checksums SQLite reads them by.
        log(f"warning: {wal} is not empty - Rekordbox is open or did not close "
            "cleanly, so its latest changes may be missing. Close it for a full read.")
    if log:
        log(f"sqlcipher3 is not installed: decrypting {source} into a temporary plain copy")
    with scratch("rekordbox-") as tmp:
        plain = os.path.join(tmp, "master.db")
        decrypt_file(source, plain, deobfuscate(BLOB))
        db = Rekordbox6Database(path=plain, db_dir=os.path.dirname(os.path.abspath(source)), unlock=False)
        try:
            yield db
        finally:
            db.close()
            db.engine.dispose()  # or Windows refuses to delete the copy


def _have_sqlcipher() -> bool:
    try:
        import sqlcipher3  # noqa: F401
    except ImportError:
        return False
    return True


def _local_db_path() -> str:
    """Where the local Rekordbox keeps `master.db`, as pyrekordbox finds it."""
    from pyrekordbox.config import get_config

    for version in ("rekordbox7", "rekordbox6"):
        path = (get_config(version) or {}).get("db_path")
        if path:
            return str(path)
    raise FileNotFoundError("No local Rekordbox 6/7 library found; pass the master.db path.")


def iter_content(db) -> Iterator:
    """Every content (track) row, across the pyrekordbox API spellings seen so far."""
    if hasattr(db, "get_content"):
        return iter(db.get_content())
    if hasattr(db, "djmd_content"):
        return iter(db.djmd_content)
    raise RuntimeError("Unrecognized pyrekordbox v6 API.")


def load_files(db_path: Optional[str] = None, *, log: Optional[Callable[[str], None]] = None) -> list[RekordboxFile]:
    """One `RekordboxFile` per content row that names a file.

    Rows without a `FolderPath` are skipped: they are streaming entries, with
    no file on disk to compare anything against.
    """
    try:
        from pyrekordbox.db6.tables import FileType
    except ImportError:  # an older pyrekordbox: codes are reported as numbers
        FileType = None

    files: list[RekordboxFile] = []
    with open_database(db_path, log=log) as db:
        for row in iter_content(db):
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
