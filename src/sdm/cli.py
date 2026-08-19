"""Top-level `sdm` command.

Each feature registers one subcommand and sets `handler` on its parser to the
function that runs it. Feature `add_parser` functions import argparse only, so
building the parser (and therefore `sdm --help`) never touches pyrekordbox,
pyacoustid, ffmpeg or the network.
"""
from __future__ import annotations

import argparse
import sys
from typing import Optional

from sdm import __version__
from sdm.features import catalog, quality, rekordbox, spotify

FEATURES = (spotify, catalog, rekordbox, quality)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sdm",
        description="Music library toolchain: acquire, catalog, and reconcile with Rekordbox.",
    )
    parser.add_argument("--version", action="version", version=f"sdm {__version__}")

    subparsers = parser.add_subparsers(dest="command", metavar="<command>")
    for feature in FEATURES:
        feature.add_parser(subparsers)

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_help()
        return 2

    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
