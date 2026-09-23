"""Compute and compare chromaprint audio fingerprints via fpcalc.

Shared, because confirming a duplicate candidate by what it *sounds like* is
the one check that does not care where the track list came from — the Rekordbox
reader and the library scan both end here.

**Why this shells out to `fpcalc -raw` instead of using pyacoustid.**
`acoustid.fingerprint_file` returns the *compressed* base64 fingerprint, and
turning that back into the integers a comparison needs goes through
`chromaprint.py`, a ctypes wrapper around the native `libchromaprint` shared
library. The standalone `fpcalc.exe` does not ship that library, so the obvious
install ("put fpcalc on PATH") produced a tool that could fingerprint every
track and then not compare any of them. `fpcalc -raw` emits the integers
directly, so comparison needs nothing that computing did not already require.

fpcalc only reads the first `DEFAULT_LENGTH_SECONDS` of audio. That is a
deliberate speed/accuracy trade: it is far more than enough to tell two
recordings apart, and it keeps each fingerprint about a thousand integers long.
"""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from typing import Optional, Sequence

#: Environment variable naming the fpcalc binary, honoured by pyacoustid too.
FPCALC_ENV = "FPCALC"
FPCALC_COMMAND = "fpcalc"

#: Seconds of audio fingerprinted per track. Also fpcalc's own default.
DEFAULT_LENGTH_SECONDS = 120

#: Seconds to wait on one file before giving up on it.
FPCALC_TIMEOUT = 120


@dataclass(frozen=True)
class Fingerprint:
    duration: float             # full track duration, not the fingerprinted window
    raw: tuple[int, ...]        # uncompressed 32-bit chromaprint subfingerprints


def fpcalc_binary(fpcalc_path: Optional[str] = None) -> str:
    """The fpcalc to run: explicit path, then `$FPCALC`, then whatever is on PATH."""
    return fpcalc_path or os.environ.get(FPCALC_ENV) or FPCALC_COMMAND


def compute(
    file_path: str,
    *,
    fpcalc_path: Optional[str] = None,
    length_seconds: int = DEFAULT_LENGTH_SECONDS,
) -> Optional[Fingerprint]:
    """Fingerprint one file, or return None if *this file* could not be read.

    A missing fpcalc binary raises `RuntimeError` instead of returning None:
    "every file failed" and "the tool is not installed" need to look different
    to the caller, because the second one makes the whole run meaningless.
    """
    if not os.path.isfile(file_path):
        return None

    cmd = [
        fpcalc_binary(fpcalc_path),
        "-raw",
        "-json",
        "-length",
        str(length_seconds),
        file_path,
    ]

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            timeout=FPCALC_TIMEOUT,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"fpcalc not found (tried {cmd[0]!r}). Install the Chromaprint "
            f"command-line tool and put it on PATH, set ${FPCALC_ENV}, or pass "
            f"an explicit path."
        ) from exc
    except (subprocess.SubprocessError, OSError):
        # Timeout or a spawn failure on this one file.
        return None

    if proc.returncode != 0 or not proc.stdout:
        # Unsupported codec, corrupt file, non-audio masquerading as audio.
        return None

    try:
        payload = json.loads(proc.stdout)
        raw = tuple(int(v) for v in payload["fingerprint"])
        duration = float(payload["duration"])
    except (ValueError, TypeError, KeyError):
        return None

    if not raw:
        return None

    return Fingerprint(duration=duration, raw=raw)


def similarity(a: Fingerprint, b: Fingerprint) -> float:
    """Return a 0..1 similarity score between two chromaprint fingerprints.

    Compares the overlapping prefix via Hamming distance over the 32-bit
    subfingerprints: 1.0 is bit-identical, and unrelated audio sits near 0.5
    rather than 0, since half the bits of two random words agree by chance.
    """
    return similarity_raw(a.raw, b.raw)


def similarity_raw(raw_a: Sequence[int], raw_b: Sequence[int]) -> float:
    """`similarity` for callers that already hold the integer arrays."""
    n = min(len(raw_a), len(raw_b))
    if n == 0:
        return 0.0

    bits_diff = sum((x ^ y).bit_count() for x, y in zip(raw_a, raw_b))
    return 1.0 - bits_diff / (32.0 * n)
