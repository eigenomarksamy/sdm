import logging
import re

from tabulate import tabulate

from sdm.features.spotify.api import download_track, download_playlist_tracks
from sdm.features.spotify.config import Cfg
from sdm.features.spotify.paths import resolve_path

def print_tabulated_result(result_dict: dict) -> None:
    if result_dict:
        print(tabulate(result_dict.items(), tablefmt='pretty', stralign='left',
            headers=['track', 'status']))

def run_cli(cfg: Cfg, links: list[str]) -> int:
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
