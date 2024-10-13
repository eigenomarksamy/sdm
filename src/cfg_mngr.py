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

    def print(self):
        print(f"create_pl_folder: {self.create_pl_folder}")
        print(f"directory: {self.directory}")
        print(f"make_dirs: {self.make_dirs}")
        print(f"disable_log: {self.disable_log}")
        print(f"naming_convention: {self.naming_convention}")
        print(f"quiet: {self.quiet}")
        print(f"dry_run: {self.dry_run}")
        print(f"gui: {self.gui}")
        print(f"pre_order: {self.pre_order}")
        print(f"max_attempts: {self.max_attempts}")
        print(f"run_pp: {self.run_pp}")
