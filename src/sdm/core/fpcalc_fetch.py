"""Borrow an fpcalc binary for the length of one run, then delete it again.

`fingerprint.py` needs the Chromaprint command-line tool, and pip cannot install
it — it is a native binary, which is why `pyproject.toml` documents it in a
comment instead of listing it. That leaves a tool whose most expensive feature
refuses to start until the user has gone and found an executable by hand.

This module removes that step *without installing anything*. When fpcalc is
already available it is used and nothing is downloaded. When it is not, the
official release archive is fetched into a scratch directory under the project's
own `tmp/` root, the binary is unpacked, used for the run, and the whole
directory is removed on the way out — on success, on failure, and on Ctrl-C
alike, because the removal lives in the `finally` of `paths.scratch`.

Two consequences of "borrowed, not installed" worth keeping in mind:

  - Nothing is left on PATH, so the next run downloads again (~2 MB against a
    run measured in minutes). A user who minds should install fpcalc properly;
    that is detected first and skips all of this.
  - The scratch lives under `tmp/`, which is gitignored, so a hard kill (which
    no `finally` can survive) leaves the binary somewhere harmless and already
    excluded from the repo.

Stdlib only, deliberately: fetching the thing that makes fingerprinting possible
must not itself need a dependency the user does not have.
"""
from __future__ import annotations

import os
import platform
import shutil
import stat
import subprocess
import sys
import tarfile
import time
import urllib.request
import zipfile
from contextlib import contextmanager
from typing import Callable, Iterator, Optional

from sdm.core.fingerprint import fpcalc_binary
from sdm.core.paths import scratch

#: Pinned rather than resolved from the "latest release" API: a run should not
#: silently change which binary it uses, and the API call is one more thing to
#: fail. Bump this deliberately.
CHROMAPRINT_VERSION = "1.6.1"

_RELEASE_URL = (
    "https://github.com/acoustid/chromaprint/releases/download/"
    "v{version}/chromaprint-fpcalc-{version}-{platform}.{ext}"
)

#: Seconds to wait on the download before giving up and reporting it.
DOWNLOAD_TIMEOUT = 60

#: How hard to try to delete the borrowed binary again. See `_purge`.
_PURGE_ATTEMPTS = 10
_PURGE_DELAY = 0.5


def _platform_asset() -> tuple[str, str]:
    """Return the (platform, extension) pair naming this machine's release asset.

    Raises `RuntimeError` for a platform the project does not publish a binary
    for, so the caller can say so instead of 404-ing.
    """
    machine = platform.machine().lower()
    arm = machine in ("arm64", "aarch64")

    if sys.platform.startswith("win"):
        if arm:
            raise RuntimeError("no published fpcalc build for Windows on ARM")
        return "windows-x86_64", "zip"
    if sys.platform == "darwin":
        return "macos-universal", "tar.gz"
    if sys.platform.startswith("linux"):
        return ("linux-arm64" if arm else "linux-x86_64"), "tar.gz"

    raise RuntimeError(f"no published fpcalc build for platform {sys.platform!r}")


def download_url(version: str = CHROMAPRINT_VERSION) -> str:
    """The release asset URL for this machine."""
    name, ext = _platform_asset()
    return _RELEASE_URL.format(version=version, platform=name, ext=ext)


def _extract_fpcalc(archive: str, dest_dir: str) -> str:
    """Unpack just the fpcalc executable out of `archive` into `dest_dir`.

    The member is located by basename rather than by the archive's directory
    layout, which is version-dependent and not worth depending on.
    """
    wanted = ("fpcalc", "fpcalc.exe")

    if archive.endswith(".zip"):
        with zipfile.ZipFile(archive) as zf:
            member = next(
                (n for n in zf.namelist() if os.path.basename(n) in wanted), None
            )
            if member is None:
                raise RuntimeError("downloaded archive contained no fpcalc binary")
            target = os.path.join(dest_dir, os.path.basename(member))
            with zf.open(member) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
    else:
        with tarfile.open(archive) as tf:
            member_info = next(
                (m for m in tf.getmembers()
                 if m.isfile() and os.path.basename(m.name) in wanted),
                None,
            )
            if member_info is None:
                raise RuntimeError("downloaded archive contained no fpcalc binary")
            target = os.path.join(dest_dir, os.path.basename(member_info.name))
            src = tf.extractfile(member_info)
            if src is None:
                raise RuntimeError("downloaded archive contained no fpcalc binary")
            with src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)

    # The archive's own mode bits do not survive the selective extraction above.
    os.chmod(target, os.stat(target).st_mode | stat.S_IXUSR | stat.S_IXGRP)
    return target


def _purge(directory: str, log: Callable[[str], None]) -> None:
    """Remove the scratch directory, retrying while Windows still holds it.

    `paths.scratch` already removes the directory, but with `ignore_errors=True`
    — which on Windows quietly loses. A binary that was executed thousands of
    times over a long run can still be open when the run ends (a virus scanner
    reading the image it just saw run is the usual culprit), and `rmtree` then
    fails on a sharing violation and says nothing. Retrying for a few seconds
    covers that window, and saying so covers the rest: a temporary file that
    outlives the run is worth one line of output, not silence.
    """
    for attempt in range(_PURGE_ATTEMPTS):
        try:
            shutil.rmtree(directory)
            return
        except FileNotFoundError:
            return
        except OSError:
            if attempt + 1 < _PURGE_ATTEMPTS:
                time.sleep(_PURGE_DELAY)

    if os.path.exists(directory):
        log(f"fpcalc: could not remove {directory} (still in use); it is under "
            f"tmp/ and gitignored, so deleting it later is harmless")


def _runs(path: str) -> bool:
    """True if `path` is an fpcalc that actually executes on this machine."""
    try:
        proc = subprocess.run(
            [path, "-version"], capture_output=True, timeout=30,
            encoding="utf-8", errors="replace",
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0


@contextmanager
def borrowed_fpcalc(
    explicit_path: Optional[str] = None,
    *,
    allow_download: bool = True,
    log: Callable[[str], None] = lambda _msg: None,
) -> Iterator[Optional[str]]:
    """Yield a usable fpcalc path for the duration of the block.

    Yields the already-installed binary when there is one (nothing is downloaded
    and nothing is cleaned up), a freshly downloaded one otherwise, or `None`
    when neither is possible — the caller reports that, since it already has a
    message for "fingerprinting is unavailable".

    A downloaded binary is removed when the block exits, whatever the reason.
    """
    installed = shutil.which(fpcalc_binary(explicit_path))
    if installed:
        yield installed
        return

    if explicit_path:
        # Falling through to a download here would quietly ignore what the user
        # asked for, and they would never learn the path was wrong.
        log(f"fpcalc: {explicit_path!r} is not an executable binary")

    if not allow_download:
        yield None
        return

    try:
        url = download_url()
    except RuntimeError as exc:
        log(f"fpcalc: {exc}")
        yield None
        return

    with scratch("fpcalc") as work_dir:
        # `scratch` removes this too, but only with `ignore_errors=True`. The
        # inner `finally` is the one that actually keeps the promise; see
        # `_purge`. Both run whatever the block raises, Ctrl-C included.
        try:
            archive = os.path.join(work_dir, os.path.basename(url))
            log(f"fpcalc not found; fetching {url}")
            try:
                with urllib.request.urlopen(url, timeout=DOWNLOAD_TIMEOUT) as resp, \
                        open(archive, "wb") as fh:
                    shutil.copyfileobj(resp, fh)
                binary = _extract_fpcalc(archive, work_dir)
            except Exception as exc:  # network, archive shape, disk — all the same
                log(f"fpcalc: could not fetch a binary ({exc})")
                yield None
                return

            if not _runs(binary):
                log("fpcalc: the downloaded binary would not run on this machine")
                yield None
                return

            log(f"fpcalc: using temporary {binary} (removed when the run ends)")
            yield binary
        finally:
            _purge(work_dir, log)
