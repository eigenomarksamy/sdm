"""`sdm duplicates` — find duplicate tracks in a music folder by how they sound.

The Rekordbox feature answers "what is duplicated in my *Rekordbox library*";
this one answers "what is duplicated in *this folder*", with no database and no
USB involved. That difference is not cosmetic: a folder has only tags to go on,
so the detection is configured differently — see `sdm.core.duplicates`.

Read-only. It reports; it never moves or deletes a file.
"""
from __future__ import annotations

import argparse


def add_parser(subparsers, parents=()) -> argparse.ArgumentParser:
    p = subparsers.add_parser(
        "duplicates",
        parents=list(parents),
        help="Scan a music folder and report duplicate tracks by audio fingerprint.",
        description="Walk a music folder, group tracks whose audio fingerprints "
                    "match, and write the groups to CSV and JSON. Read-only: "
                    "nothing is moved, renamed or deleted. Needs the fpcalc "
                    "binary (Chromaprint); if none is installed, one is "
                    "borrowed into tmp/ for the run and deleted afterwards.",
    )
    p.add_argument("directory", help="Music folder to scan, searched recursively.")
    p.add_argument("--output-dir", default=None,
                   help="Write reports here instead of <out-dir>/duplicates/.")

    # Prefilter. Duration is the only dimension a folder can always supply, so
    # it is the only one on by default; the two --require flags are for
    # libraries that are known to be tagged with BPM/key and want the speed.
    p.add_argument("--duration-tolerance", type=float, default=2.0,
                   help="Seconds two tracks may differ by and still be compared "
                        "(default: %(default)s).")
    p.add_argument("--bpm-tolerance", type=float, default=0.5,
                   help="BPM two tracks may differ by, applied only when both "
                        "carry a BPM tag (default: %(default)s).")
    p.add_argument("--require-bpm", action="store_true",
                   help="Prefilter on BPM, skipping files with no BPM tag. "
                        "Much faster, but BPM tags are patchy - half the "
                        "reference library has none, and those files are "
                        "dropped before fingerprinting.")
    p.add_argument("--require-key", action="store_true",
                   help="Prefilter on musical key, skipping files with no key "
                        "tag. Same speed-up as --require-bpm at far less cost: "
                        "key tags are near-universal where BPM tags are not.")

    # Confirmation.
    p.add_argument("--fingerprint-threshold", type=float, default=0.85,
                   help="Chromaprint similarity, 0..1, at which a candidate pair "
                        "is called a duplicate (default: %(default)s).")
    p.add_argument("--skip-fingerprint", action="store_true",
                   help="Report the metadata prefilter's candidates without "
                        "fingerprinting. Fast, and noisy - useful to size a run "
                        "before committing to it.")
    p.add_argument("--fpcalc-path", help="Path to the fpcalc binary if not on PATH.")
    p.add_argument("--no-fetch-fpcalc", action="store_true",
                   help="Do not download a temporary fpcalc when none is "
                        "installed; fail instead. The download is used only for "
                        "the run and deleted again when it ends.")
    p.set_defaults(handler=_run)
    return p


def _run(args: argparse.Namespace) -> int:
    from sdm.features.duplicates.command import run

    return run(args)
