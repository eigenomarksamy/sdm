import os
import argparse
from tabulate import tabulate

def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="CLI Program to download track from Spotify.")
    parser.add_argument("--link", "-l", nargs="+", dest='link',
                        help="URL of the spotify track or playlist.")
    parser.add_argument("--output", "-o", nargs="?",
                        default=os.path.join(os.getcwd(), 'downloads'),
                        help="Path to save the downloaded track(s).")
    parser.add_argument("--sync", "-s", nargs="?", const="sync.json",
                        help="Path of sync.json file to sync local playlists "
                             "folders with Spotify playlists.")
    parser.add_argument("--folder", nargs="?", default=True,
                        help="Create a folder for the playlist "
                             "(default: True).")
    parser.add_argument("--no-make-dirs", action='store_true',
                        dest='no_make_dirs',
                        help="Disable creation of missing folders in download directory "
                             "(default: False).")
    parser.add_argument('--tf', action='store_true', dest='track_name_convention',
                        help='Select naming convention (default: Artist - Track).')
    parser.add_argument('--disable-log', action='store_true', dest='disable_log',
                        help='Disable logging (default: False).')
    parser.add_argument('--quiet', '-q', action='store_true', dest='quiet',
                        help='Run quietly (default: False).')
    parser.add_argument('--dry-run', '-n', action='store_true', dest='dry_run',
                        help='Simulate a run (default: False).')
    parser.add_argument('--disable-gui', action='store_true', dest='disable_gui',
                        help='Disable GUI (default: False).')
    parser.add_argument('--pre-order', action='store_true', dest='pre_order',
                        help='Preserve order (default: False).')
    parser.add_argument('--run-pp', action='store_true', dest='run_pp',
                        help='Run post-processing (default: False).')
    return parser.parse_args()

def print_tabulated_result(result_dict: dict) -> None:
    print(tabulate(result_dict.items(), tablefmt='pretty', stralign='left',
          headers=['track', 'status']))
