import re
import sys
import logging
from argparse import Namespace
from src.conf_manager import Cfg
from src.cli_manager import parse_arguments, print_tabulated_result
from src.dir_manager import resolve_path
from src.api_manager import download_track, download_playlist_tracks

def execute(cfg: Cfg, links: list[str]) -> int:
    for link in links:
        ret = resolve_path(cfg.directory, cfg.create_pl_folder, cfg.make_dirs)
        if re.search(r".*spotify\.com\/track\/", link):
            downloaded = download_track(link, cfg)
            if not cfg.quiet:
                print(downloaded)
        elif re.search(r".*spotify\.com\/playlist\/", link):
            downloaded = download_playlist_tracks(link, cfg)
            if not cfg.quiet:
                print_tabulated_result(downloaded)
        else:
            if not cfg.disable_log:
                logging.error(f"{link} is not a valid Spotify "
                              "track or playlist link.")
            if not cfg.quiet:
                print(f"\n{link} is not a valid Spotify "
                      "track or playlist link")
            ret = {'status': 1,
                   'details': f"{link} is not a valid Spotify "
                               "track or playlist link."}
    return ret['status']

def run(args: Namespace) -> dict:
    cfg_obj = Cfg(naming_convention=Cfg.NamingConventions.TRACK_ARTIST \
                  if args.track_name_convention \
                    else Cfg.NamingConventions.ARTIST_TRACK,
                  directory=args.output, create_pl_folder=args.folder,
                  make_dirs=not args.no_make_dirs, disable_log=args.disable_log,
                  quiet=args.quiet, dry_run=args.dry_run,
                  gui=not args.disable_gui, preserve_order=args.pre_order)
    execute(cfg_obj, args.link)

if __name__ == '__main__':
    sys.exit(run(parse_arguments()))
