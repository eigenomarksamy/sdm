"""Finding what Rekordbox's database says about a file on disk.

The file's own claims need no finding — `core.tags.read_audio_header` reads
them out of the file. Rekordbox's are rows keyed by a path that is often not
this one: scanning a USB means looking up a copy of a file the local library
knows by its original location. `RekordboxIndex` is that lookup.
"""
from __future__ import annotations

import os
from collections import defaultdict
from typing import Optional

from sdm.core.rekordbox_db import RekordboxFile


class RekordboxIndex:
    """The database row for a file on disk, and how it was matched.

    By path first: a scan of the local library finds its own rows exactly. Then
    by file name *and size*, which is how a USB copy is recognized — Rekordbox
    copies the file byte for byte when it exports, so the local row's size
    still matches (3,064 of 3,069 name matches on the reference USB). Then by
    name alone, but only when exactly one row has that name: a file retagged
    after export differs in size, not in audio. A name several rows share
    matches none of them; a wrong row would put another file's claims beside
    this one's measurement.
    """

    def __init__(self, files: list[RekordboxFile]) -> None:
        self.count = len(files)
        self._by_path: dict[str, RekordboxFile] = {}
        self._by_name_size: dict[tuple[str, int], RekordboxFile] = {}
        self._by_name: dict[str, list[RekordboxFile]] = defaultdict(list)
        for f in files:
            self._by_path.setdefault(os.path.normcase(f.file_path), f)
            name = os.path.basename(f.file_path).lower()
            self._by_name[name].append(f)
            if f.file_size:
                self._by_name_size.setdefault((name, f.file_size), f)

    def find(self, path: str) -> tuple[Optional[RekordboxFile], Optional[str]]:
        """`(row, how)` with `how` one of "path", "name+size", "name"; `(None, None)` if none."""
        row = self._by_path.get(os.path.normcase(os.path.normpath(path)))
        if row is not None:
            return row, "path"

        name = os.path.basename(path).lower()
        try:
            size = os.path.getsize(path)
        except OSError:
            size = None
        row = self._by_name_size.get((name, size)) if size else None
        if row is not None:
            return row, "name+size"

        rows = self._by_name.get(name, ())
        if len(rows) == 1:
            return rows[0], "name"
        return None, None
