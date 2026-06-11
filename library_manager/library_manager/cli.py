"""CLI entry point for library_manager."""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from dataclasses import asdict
from typing import Optional

from library_manager.duplicates import (
    DetectionConfig,
    DuplicateGroup,
    find_duplicates,
    find_duplicates_by_name,
)
from library_manager.fingerprint import Fingerprint, compute as compute_fingerprint
from library_manager.rekordbox_reader import Track, load_tracks, resolve_db_path


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="library_manager",
        description="Read a Rekordbox USB drive tracks.",
    )
    p.add_argument("--usb-path", help="Mount path of the Rekordbox USB (e.g. E:/)")
    p.add_argument("--db-path", help="Direct path to master.db (overrides --usb-path)")
    p.add_argument("--output-dir", default="./out", help="Where to write reports (default: ./out)")

    p.add_argument(
        "--export-csv",
        metavar="PATH",
        help="Export track metadata to CSV (title, artist, bpm, time, key) and exit.",
    )

    p.add_argument(
        "--duplicates-by-name",
        action="store_true",
        help="Report duplicates by matching (title, artist) only; "
             "skips the BPM/key/fingerprint pipeline.",
    )

    p.add_argument("--bpm-tolerance", type=float, default=0.5)
    p.add_argument("--duration-tolerance", type=float, default=2.0)
    p.add_argument(
        "--no-key-match",
        dest="key_must_match",
        action="store_false",
        help="Do not require Rekordbox key to match in the prefilter.",
    )
    p.add_argument("--fingerprint-threshold", type=float, default=0.85)
    p.add_argument(
        "--skip-fingerprint",
        action="store_true",
        help="Skip the fingerprint stage; report on metadata prefilter alone.",
    )
    p.add_argument("--fpcalc-path", help="Path to fpcalc binary if not on PATH.")
    return p


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)

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

    # Export mode: write CSV and exit
    if args.export_csv:
        _export_csv(args.export_csv, tracks)
        print(f"wrote {args.export_csv}")
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

    os.makedirs(args.output_dir, exist_ok=True)
    csv_path = os.path.join(args.output_dir, "duplicates.csv")
    json_path = os.path.join(args.output_dir, "duplicates.json")
    _write_csv(csv_path, groups)
    _write_json(json_path, groups)
    print(f"wrote {csv_path}")
    print(f"wrote {json_path}")
    return 0


def _export_csv(path: str, tracks: list[Track]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["title", "artist", "bpm", "time", "key"])
        for t in sorted(tracks, key=lambda x: (x.artist, x.title)):
            writer.writerow([
                t.title,
                t.artist,
                t.bpm if t.bpm is not None else "",
                t.duration_seconds if t.duration_seconds is not None else "",
                t.key or "",
            ])


def _write_csv(path: str, groups: list[DuplicateGroup]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "group_id",
            "matched_rules",
            "track_id",
            "artist",
            "title",
            "bpm",
            "key",
            "duration_seconds",
            "file_path",
        ])
        for g in groups:
            rules = "+".join(sorted(g.matched_rules))
            for t in g.tracks:
                writer.writerow([
                    g.group_id,
                    rules,
                    t.id,
                    t.artist,
                    t.title,
                    t.bpm if t.bpm is not None else "",
                    t.key or "",
                    t.duration_seconds if t.duration_seconds is not None else "",
                    t.file_path,
                ])


def _write_json(path: str, groups: list[DuplicateGroup]) -> None:
    payload = [
        {
            "group_id": g.group_id,
            "matched_rules": sorted(g.matched_rules),
            "tracks": [asdict(t) for t in g.tracks],
        }
        for g in groups
    ]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
