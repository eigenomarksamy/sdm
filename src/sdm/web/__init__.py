"""`sdm web` — a local web interface over every other command.

**Not a feature, and the difference is rule 1.** A feature may not reach into a
sibling, and this exists to drive all of them. It sits beside `cli.py` as a
second front end over the same parser and imports no feature at all: it reads
the argparse tree to build its forms (`schema.py`), runs each command as a
subprocess (`jobs.py`), and reads the reports the command leaves under `out/`
(`reports.py`). A flag added to any command shows up in the UI with no change
here, and the UI cannot offer an option the command does not have.

Local only. The server binds 127.0.0.1 and every API call needs the per-launch
token the terminal prints; `server.py` says what that defends against.

Stdlib only on the Python side, so `sdm web` works on a bare install. The page
itself is a React app built from `frontend/` into `static/`; that build needs
Node, the server does not.
"""
from __future__ import annotations

import argparse

#: Not 8765: that is the Spotify login's redirect port (`core/spotify.py`), and
#: a playlist command run from the UI has to be able to take it.
DEFAULT_PORT = 8770


def add_parser(subparsers, parents=()) -> argparse.ArgumentParser:
    p = subparsers.add_parser(
        "web",
        parents=list(parents),
        help="Open a local web interface for every command.",
        description="Serve a web interface on 127.0.0.1 that runs the other "
                    "commands, streams their output, and browses their reports: "
                    "duplicate groups with audio playback, playlist diffs split "
                    "into missing / maybe / owned, and a table of any CSV under "
                    "the output directory. Local only - nothing off this machine "
                    "can connect.",
    )
    p.add_argument("--port", type=int, default=None,
                   help=f"Port to listen on (default: {DEFAULT_PORT}, or a free "
                        f"one if that is taken). An explicit port that is taken "
                        f"is an error.")
    p.add_argument("--no-browser", action="store_true",
                   help="Print the link instead of opening a browser.")
    p.set_defaults(handler=_run)
    return p


def _run(args: argparse.Namespace) -> int:
    from sdm.web.server import serve

    return serve(port=args.port, open_browser=not args.no_browser)
