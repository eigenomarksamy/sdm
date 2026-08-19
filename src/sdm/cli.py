"""Top-level `sdm` command.

Each feature registers one subcommand and sets `handler` on its parser to the
function that runs it. Feature `add_parser` functions import argparse only, so
building the parser (and therefore `sdm --help`) never touches pyrekordbox,
pyacoustid, ffmpeg or the network.

`--out-dir` and `--tmp-dir` are shared by every subcommand via a parent parser
rather than defined on the top-level one, so they can be typed after the
subcommand where they read naturally: `sdm catalog --out-dir ./reports <dir>`.
"""
from __future__ import annotations

import argparse
import sys
from typing import Optional

from sdm import __version__
from sdm.core import paths
from sdm.features import catalog, quality, rekordbox, spotify

FEATURES = (spotify, catalog, rekordbox, quality)


def _common_parser() -> argparse.ArgumentParser:
    """Options every subcommand inherits. `add_help=False` — the child owns -h."""
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--out-dir", default=None, metavar="DIR",
        help=f"Root for generated reports (default: {paths.DEFAULT_OUT_DIR}, "
             f"or ${paths.OUT_DIR_ENV}). Each feature writes to <DIR>/<feature>/.",
    )
    common.add_argument(
        "--tmp-dir", default=None, metavar="DIR",
        help=f"Root for scratch files, cleaned up on exit "
             f"(default: {paths.DEFAULT_TMP_DIR}, or ${paths.TMP_DIR_ENV}).",
    )
    return common


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sdm",
        description="Music library toolchain: acquire, catalog, and reconcile with Rekordbox.",
    )
    parser.add_argument("--version", action="version", version=f"sdm {__version__}")

    common = _common_parser()
    subparsers = parser.add_subparsers(dest="command", metavar="<command>")
    for feature in FEATURES:
        feature.add_parser(subparsers, parents=[common])

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_help()
        return 2

    # Set the roots before any handler resolves a destination against them.
    paths.configure(args.out_dir, args.tmp_dir)

    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
