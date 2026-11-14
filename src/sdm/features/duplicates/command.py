"""Runs the `sdm duplicates` subcommand.

Walk -> read tags -> prefilter -> fingerprint -> report. The only part specific
to this feature is the first step and the defaults it picks for the detector;
everything after that is `sdm.core.duplicates`, shared with the Rekordbox
feature so both produce the same report.
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import Optional

from sdm.core.duplicates import DetectionConfig, find_duplicates, fingerprint_preflight
from sdm.core.fingerprint import Fingerprint, compute as compute_fingerprint
from sdm.core.fpcalc_fetch import borrowed_fpcalc
from sdm.core.paths import out_dir
from sdm.core.report import ensure_dir, write_duplicate_report
from sdm.core.tags import tracks_from_files
from sdm.core.track import Track, iter_audio_files


def run(args: argparse.Namespace) -> int:
    directory = args.directory
    if not os.path.isdir(directory):
        print(f"error: not a directory: {directory}", file=sys.stderr)
        return 2

    files = sorted(iter_audio_files(directory))
    print(f"scanning {directory}")
    if not files:
        print("no audio files found")
        return 0

    tracks = tracks_from_files(files, log=print)
    print(f"read {len(tracks)} track(s) from {len(files)} audio file(s)")

    config = DetectionConfig(
        bpm_tolerance=args.bpm_tolerance,
        duration_tolerance=args.duration_tolerance,
        key_must_match=args.require_key,
        require_bpm=args.require_bpm,
        fingerprint_threshold=args.fingerprint_threshold,
        skip_fingerprint=args.skip_fingerprint,
    )

    # The binary is resolved once for the whole run rather than per call: if it
    # had to be downloaded, everything that needs it has to happen inside this
    # block, because leaving the block deletes it again.
    with borrowed_fpcalc(
        args.fpcalc_path,
        allow_download=not config.skip_fingerprint and not args.no_fetch_fpcalc,
        log=lambda msg: print(msg),
    ) as fpcalc_path:

        def fingerprint_fn(t: Track) -> Optional[Fingerprint]:
            return compute_fingerprint(t.file_path, fpcalc_path=fpcalc_path)

        if not config.skip_fingerprint:
            error = fingerprint_preflight(tracks, fingerprint_fn)
            if error:
                print(error, file=sys.stderr)
                return 1

        try:
            groups = find_duplicates(
                tracks,
                config,
                fingerprint_fn=None if config.skip_fingerprint else fingerprint_fn,
                progress=lambda msg: print(msg),
            )
        except RuntimeError as exc:
            # fpcalc went missing mid-run. Say so once rather than per file.
            print(f"error: {exc}", file=sys.stderr)
            return 1

    print(f"found {len(groups)} duplicate group(s)")
    if config.skip_fingerprint:
        print("note: --skip-fingerprint, so these are metadata candidates, not confirmed duplicates")

    report_dir = ensure_dir(args.output_dir) if args.output_dir else out_dir("duplicates")
    csv_path, json_path = write_duplicate_report(report_dir, groups)
    print(f"wrote {csv_path}")
    print(f"wrote {json_path}")
    return 0
