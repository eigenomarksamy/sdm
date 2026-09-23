"""Where output goes.

`report.py` decides *how* a file is written; this module decides *where*. Every
feature that emits an artifact resolves its destination here, so a run leaves
its reports in one predictable place instead of scattering them across whatever
directory the command happened to be invoked from.

Two roots, both cwd-relative by default and both already in `.gitignore`:

    ./out/<feature>/   reports meant to be kept, diffed, and looked at
    ./tmp/             scratch that is deleted again before the command exits

Precedence for the roots, strongest first: an explicit `--out-dir`/`--tmp-dir`,
then `SDM_OUT_DIR`/`SDM_TMP_DIR` in the environment, then the defaults above.
The roots are process-global because they are a property of the invocation, not
of one feature — `cli.py` calls `configure` once from the parsed arguments.

Downloaded audio is deliberately *not* routed through here. It is the product,
not a report, and belongs wherever the user pointed `--output`.

Stdlib only, so `add_parser` can import this without pulling in an optional
dependency.
"""
from __future__ import annotations

import os
import shutil
import tempfile
from contextlib import contextmanager
from typing import Iterator, Optional

OUT_DIR_ENV = "SDM_OUT_DIR"
TMP_DIR_ENV = "SDM_TMP_DIR"

DEFAULT_OUT_DIR = "./out"
DEFAULT_TMP_DIR = "./tmp"

_out_root: Optional[str] = None
_tmp_root: Optional[str] = None


def configure(out_dir: Optional[str] = None, tmp_dir: Optional[str] = None) -> None:
    """Set the roots for this run. Called once by `cli.py`; `None` means "unset"."""
    global _out_root, _tmp_root
    if out_dir:
        _out_root = out_dir
    if tmp_dir:
        _tmp_root = tmp_dir


def out_root() -> str:
    """The run's output root, resolved but not created."""
    return _out_root or os.environ.get(OUT_DIR_ENV) or DEFAULT_OUT_DIR


def tmp_root() -> str:
    """The run's scratch root, resolved but not created."""
    return _tmp_root or os.environ.get(TMP_DIR_ENV) or DEFAULT_TMP_DIR


def out_dir(feature: Optional[str] = None) -> str:
    """Return `out/<feature>/`, creating it. Omit `feature` for the root itself."""
    path = out_root() if feature is None else os.path.join(out_root(), feature)
    os.makedirs(path, exist_ok=True)
    return path


def tmp_dir() -> str:
    """Return the scratch root, creating it."""
    path = tmp_root()
    os.makedirs(path, exist_ok=True)
    return path


def resolve_output(path: Optional[str], feature: str, default_name: str) -> str:
    """Resolve a user-supplied output path against the feature's output directory.

    Three cases, and the distinction is the point — unifying the defaults must
    not take away the ability to write somewhere specific:

      - `None`            -> `out/<feature>/<default_name>`
      - a bare filename   -> `out/<feature>/<that name>`
      - anything with a directory component, absolute or relative, is honoured
        verbatim so `--export-csv D:/reports/x.csv` still lands on D:.
    """
    if path is None:
        return os.path.join(out_dir(feature), default_name)

    head, tail = os.path.split(path)
    if head:
        parent = os.path.dirname(os.path.abspath(path))
        os.makedirs(parent, exist_ok=True)
        return path

    return os.path.join(out_dir(feature), tail)


@contextmanager
def scratch(prefix: str) -> Iterator[str]:
    """A temporary directory under the tmp root, removed on exit.

    Use this instead of `tempfile.mkdtemp()` directly so intermediate files stay
    inside the project's own tmp root rather than the system temp directory,
    where they are invisible when something goes wrong mid-run.
    """
    path = tempfile.mkdtemp(prefix=f"{prefix}-", dir=tmp_dir())
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)
