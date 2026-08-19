"""Runs the `sdm rekordbox` subcommand."""
from __future__ import annotations

import argparse
import os
import sys
from dataclasses import asdict
from typing import Optional

from sdm.core.paths import out_dir, resolve_output
from sdm.core.report import ensure_dir, write_csv, write_json
from sdm.features.rekordbox.duplicates import (
    DetectionConfig,
    DuplicateGroup,
    find_duplicates,
    find_duplicates_by_name,
)
from sdm.features.rekordbox.fingerprint import Fingerprint, compute as compute_fingerprint
from sdm.features.rekordbox.reader import Track, load_tracks, resolve_db_path


def run(args: argparse.Namespace) -> int:
    try:
        db_path = resolve_db_path(args.usb_path, args.db_path)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(f"reading tracks from {db_path}")
    try:
        tracks = load_tracks(db_path, usb_path=args.usb_path)
    except (FileNotFoundError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"loaded {len(tracks)} track(s)")

    # Export mode: write CSV and exit. `""` is the bare `--export-csv` flag,
    # which means "the default name"; `None` means the flag was not given.
    if args.export_csv is not None:
        export_path = resolve_output(args.export_csv or None, "rekordbox", "tracks.csv")
        _export_csv(export_path, tracks)
        print(f"wrote {export_path}")
        return 0

    if args.duplicates_by_name:
        groups = find_duplicates_by_name(tracks, progress=lambda msg: print(msg))
    else:
        config = DetectionConfig(
            bpm_tolerance=args.bpm_tolerance,
            duration_tolerance=args.duration_tolerance,
            key_must_match=args.key_must_match,
            fingerprint_threshold=args.fingerprint_threshold,
            skip_fingerprint=args.skip_fingerprint,
        )

        def fingerprint_fn(t: Track) -> Optional[Fingerprint]:
            return compute_fingerprint(t.file_path, fpcalc_path=args.fpcalc_path)

        groups = find_duplicates(
            tracks,
            config,
            fingerprint_fn=None if config.skip_fingerprint else fingerprint_fn,
            progress=lambda msg: print(msg),
        )

    print(f"found {len(groups)} duplicate group(s)")

    report_dir = ensure_dir(args.output_dir) if args.output_dir else out_dir("rekordbox")
    csv_path = os.path.join(report_dir, "duplicates.csv")
    json_path = os.path.join(report_dir, "duplicates.json")
    _write_csv(csv_path, groups)
    _write_json(json_path, groups)
    print(f"wrote {csv_path}")
    print(f"wrote {json_path}")
    return 0


def _export_csv(path: str, tracks: list[Track]) -> None:
    write_csv(
        path,
        ["title", "artist", "bpm", "time", "key"],
        (
            [
                t.title,
                t.artist,
                t.bpm if t.bpm is not None else "",
                t.duration_seconds if t.duration_seconds is not None else "",
                t.key or "",
            ]
            for t in sorted(tracks, key=lambda x: (x.artist, x.title))
        ),
    )


def _write_csv(path: str, groups: list[DuplicateGroup]) -> None:
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
        path,
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


def _write_json(path: str, groups: list[DuplicateGroup]) -> None:
    write_json(
        path,
        [
            {
                "group_id": g.group_id,
                "matched_rules": sorted(g.matched_rules),
                "tracks": [asdict(t) for t in g.tracks],
            }
            for g in groups
        ],
    )
