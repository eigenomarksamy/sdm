"""Report writers.

Every feature that emits a report goes through here, so encoding and newline
handling are decided once. On Windows the `newline=""` argument is what keeps
`csv` from writing blank lines between rows.
"""
from __future__ import annotations

import csv
import json
import os
from typing import Any, Iterable, Sequence


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
