"""Compute and compare chromaprint audio fingerprints via fpcalc."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Fingerprint:
    duration: float
    fingerprint: str   # base64-encoded chromaprint string from fpcalc


def compute(file_path: str, *, fpcalc_path: Optional[str] = None) -> Optional[Fingerprint]:
    """Run fpcalc on the file and return its Fingerprint, or None on failure."""
    if not os.path.isfile(file_path):
        return None

    if fpcalc_path:
        os.environ["FPCALC"] = fpcalc_path

    try:
        import acoustid
    except ImportError as exc:
        raise RuntimeError(
            "pyacoustid is required. Install with: pip install pyacoustid"
        ) from exc

    try:
        duration, fp = acoustid.fingerprint_file(file_path)
    except acoustid.FingerprintGenerationError:
        return None
    except Exception:
        # fpcalc failure (binary missing, unsupported codec, etc.)
        return None

    if isinstance(fp, bytes):
        fp = fp.decode("ascii", errors="replace")

    return Fingerprint(duration=float(duration), fingerprint=fp)


def similarity(a: Fingerprint, b: Fingerprint) -> float:
    """Return a 0..1 similarity score between two chromaprint fingerprints.

    Decodes each base64 fingerprint to its int32 array and compares the
    overlapping prefix via Hamming distance on the 32-bit subfingerprints.
    """
    try:
        import chromaprint  # ships inside pyacoustid
    except ImportError as exc:
        raise RuntimeError(
            "pyacoustid (which provides chromaprint) is required."
        ) from exc

    raw_a, _ = chromaprint.decode_fingerprint(_to_bytes(a.fingerprint))
    raw_b, _ = chromaprint.decode_fingerprint(_to_bytes(b.fingerprint))

    n = min(len(raw_a), len(raw_b))
    if n == 0:
        return 0.0

    bits_diff = sum((raw_a[i] ^ raw_b[i]).bit_count() for i in range(n))
    return 1.0 - bits_diff / (32.0 * n)


def _to_bytes(fp) -> bytes:
    return fp.encode("ascii") if isinstance(fp, str) else fp
