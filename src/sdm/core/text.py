"""Title and artist normalization used when matching tracks by name.

Two strictnesses live here on purpose, because the features that use them have
different tolerance for false positives:

- `normalize_loose` also strips mix suffixes ("Track (Original Mix)" ->
  "track"). The catalog works from filesystem tags alone, where the same track
  is routinely tagged with and without the suffix.
- `normalize_simple` only casefolds and collapses whitespace. The Rekordbox
  feature has BPM/key/duration to fall back on, so it errs toward keeping
  distinct releases distinct.

Keeping both in one module makes the divergence visible instead of leaving it
buried in two unrelated files.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Optional

#: Mix suffixes stripped by `normalize_loose`. Extend as the library needs it.
MIX_SUFFIXES = [
    "original mix",
    # add more later if needed:
    # "extended mix",
    # "club mix",
    # "radio edit",
    # "dub mix",
]


def normalize_text(value: Optional[str]) -> str:
    """Unicode-normalize, casefold, and collapse whitespace."""
    value = value or ""
    value = unicodedata.normalize("NFKC", value)
    value = value.casefold()
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def normalize_loose(title: Optional[str]) -> str:
    """`normalize_text` plus repeated removal of any trailing mix suffix.

    Handles both bracketed and dash-separated forms, and loops so that a title
    carrying more than one suffix is fully reduced.
    """
    title = normalize_text(title)

    suffix_pattern = "|".join(re.escape(suffix) for suffix in MIX_SUFFIXES)

    patterns = [
        # Track Name (Original Mix)
        rf"\s*[\(\[\{{]\s*({suffix_pattern})\s*[\)\]\}}]\s*$",

        # Track Name - Original Mix
        rf"\s*[-–—]\s*({suffix_pattern})\s*$",
    ]

    changed = True
    while changed:
        old_title = title

        for pattern in patterns:
            title = re.sub(pattern, "", title, flags=re.IGNORECASE)

        title = re.sub(r"\s+", " ", title).strip()

        changed = title != old_title

    return title


def normalize_simple(value: Optional[str]) -> str:
    """Lowercase and collapse whitespace. No suffix handling."""
    return " ".join((value or "").strip().lower().split())
