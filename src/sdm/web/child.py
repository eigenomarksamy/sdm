"""What the web UI actually runs: `sdm`, plus a way to be stopped politely.

`python -m sdm.web.child <argv>` is `sdm <argv>` with one difference. A cancel
from the UI arrives as CTRL_BREAK on Windows, whose default action ends the
process on the spot — no `finally` blocks, so a borrowed fpcalc is left behind in
tmp/ (see `core/fpcalc_fetch.py`). Mapping it to KeyboardInterrupt makes a cancel
behave exactly like Ctrl-C in a terminal. Elsewhere the cancel is SIGINT, which
Python already turns into KeyboardInterrupt.
"""
from __future__ import annotations

import signal
import sys

from sdm.cli import main

#: The shell's convention for "stopped by Ctrl-C"; `jobs.py` reads it as cancelled.
CANCELLED_EXIT = 130


def run() -> int:
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, signal.default_int_handler)
    try:
        return main(sys.argv[1:])
    except KeyboardInterrupt:
        print("cancelled", file=sys.stderr)
        return CANCELLED_EXIT


if __name__ == "__main__":
    sys.exit(run())
