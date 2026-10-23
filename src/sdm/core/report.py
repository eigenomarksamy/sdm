"""Report writers.

Every feature that emits a report goes through here, so encoding and newline
handling are decided once. On Windows the `newline=""` argument is what keeps
`csv` from writing blank lines between rows.

A report must survive a string UTF-8 cannot encode: a lone surrogate. NTFS
stores names as unvalidated UTF-16, so a file named with half a surrogate pair
is legal, `os.listdir` returns it as `'\\ud800'`, and a strict writer crashed
on it partway through a report. Reports write it as the six characters
`\\ud800` instead (`REPORT_ERRORS`) — what `cli.main` prints for it too. In
JSON that is no approximation: inside a string it is JSON's own escape for the
code point, and reads back exactly. The catalog sidecar is the exception, see
`write_lines`.
"""
from __future__ import annotations

import csv
import json
import os
from dataclasses import asdict
from typing import IO, TYPE_CHECKING, Any, Iterable, Sequence

if TYPE_CHECKING:
    from sdm.core.duplicates import DuplicateGroup

#: How a report writes what UTF-8 cannot encode. See the module docstring.
REPORT_ERRORS = "backslashreplace"


def open_report(path: str, *, encoding: str = "utf-8") -> IO[str]:
    """Open `path` for a CSV report: `newline=""`, UTF-8, `REPORT_ERRORS`.

    For a writer that streams rows itself (`analyze`) rather than handing them
    to `write_csv`, so its files are written exactly as everyone else's.
    """
    return open(path, "w", newline="", encoding=encoding, errors=REPORT_ERRORS)


def write_csv(
    path: str,
    header: Sequence[str],
    rows: Iterable[Sequence[Any]],
    *,
    encoding: str = "utf-8",
) -> None:
    """Write `header` followed by `rows` as UTF-8 CSV.

    Pass `encoding="utf-8-sig"` for a file meant to be opened in Excel, which
    reads a UTF-8 CSV without a byte-order mark as the ANSI code page and turns
    "Súcubo" into "SÃºcubo".
    """
    with open_report(path, encoding=encoding) as f:
        writer = csv.writer(f)
        writer.writerow(header)
        for row in rows:
            writer.writerow(row)


def write_json(path: str, payload: Any) -> None:
    """Write `payload` as indented UTF-8 JSON, leaving non-ASCII characters intact."""
    with open(path, "w", encoding="utf-8", errors=REPORT_ERRORS) as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


def write_lines(path: str, lines: Iterable[str]) -> None:
    """Write one string per line. Used for the catalog's cross-validation sidecar.

    `surrogatepass`, not `REPORT_ERRORS`: the sidecar is compared against a
    fresh walk of the directory, so it must hold each path exactly. Escaped,
    a file named `a` + U+D800 + `.mp3` and a file `ud800.mp3` in a folder `a`
    would both write `a\\ud800.mp3`. The cost is that a line holding a lone
    surrogate is not valid UTF-8, and an editor shows replacement characters.
    """
    with open(path, "w", newline="", encoding="utf-8", errors="surrogatepass") as f:
        for line in lines:
            f.write(f"{line}\n")


def read_lines(path: str) -> list[str]:
    """Read a file written by `write_lines` back into a list, surrogates intact."""
    with open(path, "r", encoding="utf-8", errors="surrogatepass") as f:
        return [line.rstrip("\n") for line in f]


def ensure_dir(path: str) -> str:
    """Create `path` if missing and return it."""
    os.makedirs(path, exist_ok=True)
    return path


def write_duplicate_report(
    report_dir: str, groups: Iterable["DuplicateGroup"]
) -> tuple[str, str]:
    """Write `duplicates.csv` and `duplicates.json` into `report_dir`.

    One writer for every feature that detects duplicates, so a report from a
    folder scan and one from a Rekordbox library have the same shape and can be
    diffed against each other.
    """
    groups = list(groups)
    csv_path = os.path.join(report_dir, "duplicates.csv")
    json_path = os.path.join(report_dir, "duplicates.json")

    def rows():
        for g in groups:
            rules = "+".join(sorted(g.matched_rules))
            for t in g.tracks:
                yield [
                    g.group_id,
                    rules,
                    t.id,
                    t.artist,
                    t.title,
                    t.bpm if t.bpm is not None else "",
                    t.key or "",
                    t.duration_seconds if t.duration_seconds is not None else "",
                    t.file_path,
                ]

    write_csv(
        csv_path,
        [
            "group_id",
            "matched_rules",
            "track_id",
            "artist",
            "title",
            "bpm",
            "key",
            "duration_seconds",
            "file_path",
        ],
        rows(),
    )

    write_json(
        json_path,
        [
            {
                "group_id": g.group_id,
                "matched_rules": sorted(g.matched_rules),
                "tracks": [asdict(t) for t in g.tracks],
            }
            for g in groups
        ],
    )

    return csv_path, json_path
