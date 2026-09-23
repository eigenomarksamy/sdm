"""Report writers.

Every feature that emits a report goes through here, so encoding and newline
handling are decided once. On Windows the `newline=""` argument is what keeps
`csv` from writing blank lines between rows.
"""
from __future__ import annotations

import csv
import json
import os
from dataclasses import asdict
from typing import TYPE_CHECKING, Any, Iterable, Sequence

if TYPE_CHECKING:
    from sdm.core.duplicates import DuplicateGroup


def write_csv(path: str, header: Sequence[str], rows: Iterable[Sequence[Any]]) -> None:
    """Write `header` followed by `rows` as UTF-8 CSV."""
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        for row in rows:
            writer.writerow(row)


def write_json(path: str, payload: Any) -> None:
    """Write `payload` as indented UTF-8 JSON, leaving non-ASCII characters intact."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


def write_lines(path: str, lines: Iterable[str]) -> None:
    """Write one string per line. Used for the catalog's cross-validation sidecar."""
    with open(path, "w", newline="", encoding="utf-8") as f:
        for line in lines:
            f.write(f"{line}\n")


def read_lines(path: str) -> list[str]:
    """Read a file written by `write_lines` back into a list."""
    with open(path, "r", encoding="utf-8") as f:
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
