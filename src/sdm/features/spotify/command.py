from argparse import Namespace

from sdm.features.spotify.config import Cfg
from sdm.features.spotify.runner import run_cli


def run(args: Namespace) -> dict:
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
