"""The reports under the output root, read for the web UI.

Generic on purpose: a CSV comes back as rows, anything else as its bytes. The
formats belong to the features that write them, so the dedicated views
(duplicate groups, playlist diffs) interpret those rows in the browser, the
way a person reads the file, and nothing here imports a feature to do it.

CSVs are paged server-side, because some are large: `analyze --export-beats`
writes millions of rows. A file under `MEMORY_LIMIT` is parsed once and kept,
so filtering and sorting are cheap; a larger one is only ever streamed, which
pages it but cannot sort or filter it.
"""
from __future__ import annotations

import csv
import os
import threading
from collections import OrderedDict
from typing import Iterable, Optional

#: Files above this are paged by streaming rather than loaded.
MEMORY_LIMIT = 64 * 1024 * 1024

#: Parsed files kept in memory at once.
CACHE_ENTRIES = 6

MAX_PAGE = 50_000


def list_reports(root: str) -> list[dict]:
    """Every file under `root`, newest first, with its path relative to `root`."""
    files = []
    for dirpath, _, names in os.walk(root):
        for name in names:
            path = os.path.join(dirpath, name)
            try:
                stat = os.stat(path)
            except OSError:
                continue
            rel = os.path.relpath(path, root).replace(os.sep, "/")
            files.append({
                "rel": rel,
                "name": name,
                "folder": rel.rsplit("/", 1)[0] if "/" in rel else "",
                "size": stat.st_size,
                "mtime": stat.st_mtime,
            })
    files.sort(key=lambda f: f["mtime"], reverse=True)
    return files


def resolve(root: str, path: str, also_allowed: Iterable[str] = ()) -> str:
    """The absolute file `path` names, if the UI may read it.

    A path relative to `root` must stay inside it. An absolute path is accepted
    only if a job reported writing it (`also_allowed`, normcased), which is what
    lets a run with `--output-dir D:/elsewhere` still be opened in the UI.
    """
    if not path:
        raise PermissionError("no report path given")
    if os.path.isabs(path):
        full = os.path.abspath(path)
        if os.path.normcase(full) not in set(also_allowed):
            raise PermissionError("only reports under the output root, or written by a job, can be opened")
    else:
        full = os.path.abspath(os.path.join(root, path))
        if not is_inside(root, full):
            raise PermissionError("path escapes the output root")
    if not os.path.isfile(full):
        raise FileNotFoundError(f"no such report: {path}")
    return full


def is_inside(root: str, path: str) -> bool:
    try:
        root_n = os.path.normcase(os.path.abspath(root))
        return os.path.commonpath([root_n, os.path.normcase(os.path.abspath(path))]) == root_n
    except ValueError:  # different drives
        return False


class TableReader:
    """Pages of a CSV, with a small cache of parsed files keyed by size and mtime."""

    def __init__(self) -> None:
        self._cache: "OrderedDict[str, tuple[tuple, list[str], list[list[str]]]]" = OrderedDict()
        self._totals: dict[str, tuple[tuple, int]] = {}
        self._lock = threading.Lock()

    def page(
        self,
        path: str,
        offset: int = 0,
        limit: int = 100,
        query: str = "",
        sort: Optional[int] = None,
        descending: bool = False,
    ) -> dict:
        offset = max(offset, 0)
        limit = min(max(limit, 1), MAX_PAGE)
        stamp = _stamp(path)
        if stamp[0] > MEMORY_LIMIT:
            return self._streamed(path, stamp, offset, limit)

        header, rows = self._load(path, stamp)
        total = len(rows)
        if query:
            needle = query.casefold()
            rows = [r for r in rows if needle in "\x1f".join(r).casefold()]
        if sort is not None and 0 <= sort < len(header):
            # Blank cells last in either direction: "highest BPM first" should
            # not open on the tracks that have no BPM at all.
            def cell(row: list[str]) -> str:
                return row[sort].strip() if sort < len(row) else ""

            filled = [r for r in rows if cell(r)]
            blank = [r for r in rows if not cell(r)]
            rows = sorted(filled, key=lambda r: _sort_key(cell(r)), reverse=descending) + blank
        return {
            "header": header,
            "rows": rows[offset:offset + limit],
            "total": total,
            "matched": len(rows),
            "offset": offset,
            "mode": "memory",
        }

    def _load(self, path: str, stamp: tuple) -> tuple[list[str], list[list[str]]]:
        with self._lock:
            cached = self._cache.get(path)
            if cached and cached[0] == stamp:
                self._cache.move_to_end(path)
                return cached[1], cached[2]
        with _open(path) as f:
            reader = csv.reader(f)
            header = next(reader, [])
            rows = list(reader)
        with self._lock:
            self._cache[path] = (stamp, header, rows)
            self._cache.move_to_end(path)
            while len(self._cache) > CACHE_ENTRIES:
                self._cache.popitem(last=False)
        return header, rows

    def _streamed(self, path: str, stamp: tuple, offset: int, limit: int) -> dict:
        rows = []
        with _open(path) as f:
            reader = csv.reader(f)
            header = next(reader, [])
            for index, row in enumerate(reader):
                if index >= offset + limit:
                    break
                if index >= offset:
                    rows.append(row)
        return {
            "header": header,
            "rows": rows,
            "total": self._count(path, stamp),
            "matched": None,
            "offset": offset,
            "mode": "stream",
        }

    def _count(self, path: str, stamp: tuple) -> int:
        with self._lock:
            known = self._totals.get(path)
            if known and known[0] == stamp:
                return known[1]
        with _open(path) as f:
            total = max(sum(1 for _ in csv.reader(f)) - 1, 0)
        with self._lock:
            self._totals[path] = (stamp, total)
        return total


def _open(path: str):
    # utf-8-sig: the playlist export is written with a BOM for Excel, and a BOM
    # left in would become part of the first column's name.
    return open(path, "r", newline="", encoding="utf-8-sig", errors="replace")


def _stamp(path: str) -> tuple:
    stat = os.stat(path)
    return (stat.st_size, stat.st_mtime_ns)


def _sort_key(value: str) -> tuple:
    """Numbers before text, numbers by value: "9" sorts before "10"."""
    try:
        return (0, float(value), "")
    except ValueError:
        return (1, 0.0, value.casefold())
