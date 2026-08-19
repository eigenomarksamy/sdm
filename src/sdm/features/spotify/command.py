"""Runs the `sdm download` subcommand."""
from __future__ import annotations

import logging
import os
from argparse import Namespace

from sdm.core.paths import out_dir
from sdm.features.spotify.config import Cfg
from sdm.features.spotify.runner import run_cli

LOG_FILE = "download.log"


def _configure_logging() -> str:
    """Point the root logger at `<out-dir>/logs/download.log` and return the path.

    `api.py` and `runner.py` have always called `logging.error`/`logging.info`,
    but nothing ever configured a handler, so every one of those records went
    nowhere. This gives them a destination. Appends, so a run's failures can be
    compared against the previous run's.
    """
    log_path = os.path.join(out_dir("logs"), LOG_FILE)
    logging.basicConfig(
        filename=log_path,
        filemode="a",
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        force=True,
    )
    return log_path


def run(args: Namespace) -> dict:
    if not args.disable_log:
        log_path = _configure_logging()
        if not args.quiet:
            print(f"logging to {log_path}")

    cfg_obj = Cfg(naming_convention=Cfg.NamingConventions.TRACK_ARTIST \
                  if args.track_name_convention \
                    else Cfg.NamingConventions.ARTIST_TRACK,
                  directory=args.output, create_pl_folder=args.folder,
                  make_dirs=not args.no_make_dirs, disable_log=args.disable_log,
                  quiet=args.quiet, dry_run=args.dry_run,
                  gui=not args.disable_gui, preserve_order=args.pre_order)
    if not cfg_obj.gui:
        run_cli(cfg_obj, args.link)
    else:
        pass
