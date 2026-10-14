"""List the tracks in a folder whose tags lack a title, an artist, or both.

The catalog export already reads these two fields, but it writes "Unknown" for
a gap, so the gaps cannot be recovered from its CSV: a track genuinely titled
"Unknown" and a track with no title tag come out the same, and so does a file
that could not be parsed at all. This reads through `read_title_artist_raw`,
which keeps all three apart.

It covers every format in `AUDIO_EXTS`, not just the MP3s the export covers.
The files most likely to carry no tags at all are WAV and AIFF, which an
MP3-only pass would never see.

Read-only, like the rest of `catalog`: it says which files need tagging and
leaves the tagging to whoever reads the report.
"""
from __future__ import annotations

import os
import sys
from typing import Optional

from sdm.core.paths import resolve_output
from sdm.core.report import write_csv
from sdm.core.tags import read_title_artist_raw
from sdm.core.track import iter_audio_files


def _present(value: Optional[str]) -> bool:
    """A tag holding only whitespace names nothing, so it counts as missing."""
    return value is not None and value.strip() != ""


def find_missing(directory: str) -> tuple[int, list[dict]]:
    """Return how many audio files were scanned, and a row per file missing a field.

    `missing` is `title`, `artist` or `title+artist`. A file that could not be
    read at all is missing both, and carries the reason in `error`.
    """
    files = sorted(iter_audio_files(directory))
    rows = []
    for filepath in files:
        title, artist, error = read_title_artist_raw(filepath)
        missing = [
            name
            for name, value in (("title", title), ("artist", artist))
            if not _present(value)
        ]
        if missing:
            rows.append({
                "missing": "+".join(missing),
                "title": title if _present(title) else "",
                "artist": artist if _present(artist) else "",
                "filepath": filepath,
                "error": error or "",
            })
    return len(files), rows


def run(directory: str, output_csv: Optional[str] = None) -> int:
    """Scan, write the CSV, print the list and a summary. Returns an exit code."""
    if not os.path.isdir(directory):
        print(f"error: not a directory: {directory}", file=sys.stderr)
        return 2

    folder_name = os.path.basename(os.path.normpath(directory))
    output_csv = resolve_output(output_csv, "catalog", f"missing_metadata_{folder_name}.csv")

    scanned, rows = find_missing(directory)

    # Written even when empty, so a rerun after fixing the tags replaces the
    # old list instead of leaving it behind looking current.
    write_csv(
        output_csv,
        ["#", "missing", "track name", "artist", "filepath", "error"],
        (
            [index, row["missing"], row["title"], row["artist"], row["filepath"], row["error"]]
            for index, row in enumerate(rows, start=1)
        ),
    )

    for row in rows:
        suffix = f"  (unreadable: {row['error']})" if row["error"] else ""
        print(f"{row['missing']:<13} {row['filepath']}{suffix}")

    if not rows:
        print(f"all {scanned} audio file(s) have a title and an artist")
    else:
        counts = {kind: 0 for kind in ("title", "artist", "title+artist")}
        for row in rows:
            counts[row["missing"]] += 1
        unreadable = sum(1 for row in rows if row["error"])
        print(
            f"{len(rows)} of {scanned} audio file(s) missing metadata: "
            f"{counts['title']} title only, {counts['artist']} artist only, "
            f"{counts['title+artist']} both"
            + (f" ({unreadable} could not be read)" if unreadable else "")
        )
    print(f"wrote {output_csv}")
    return 0
