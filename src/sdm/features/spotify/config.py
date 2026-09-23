import os

class Cfg:

    class NamingConventions:
        TRACK_ARTIST = 1
        ARTIST_TRACK = 2

    def __init__(self, directory: os.PathLike, create_pl_folder: bool = True,
                 make_dirs: bool = True, disable_log: bool = False,
                 quiet: bool = False, dry_run: bool = False,
                 gui: bool = True, preserve_order: bool = False,
                 naming_convention: NamingConventions = NamingConventions.ARTIST_TRACK,
                 max_attempts: int = 3, run_pp: bool = False) -> None:
        self.naming_convention = naming_convention
        self.directory = directory
        self.create_pl_folder = create_pl_folder
        self.make_dirs = make_dirs
        self.disable_log = disable_log
        self.quiet = quiet
        self.dry_run = dry_run
        self.gui = gui
        self.pre_order = preserve_order
        self.max_attempts = max_attempts
        self.run_pp = run_pp

def print(obj) -> None:
    attrs = vars(obj)
    print(', '.join("%s: %s" % item for item in attrs.items()))
