"""Is the file that matched a playlist track by name actually that track?

A title and an artist are a claim the file makes about itself. Three kinds of
file make it falsely, and each is common in a library built from rips:

- **Something else under the track's name.** A DJ mix, a podcast episode or a
  whole album saved as "Artist - Title". The reference library has a
  122-minute and a 59-minute file named like single tracks.
- **A piece of the track.** A 30-second preview clip, or a download that
  stopped early.
- **A damaged file.** One mutagen cannot parse, or one that holds less audio
  than its own header describes.

So a file is checked only once it has matched by name, and a file that fails
turns the match into `mismatch`: not owned, with the reason. Only matched files
are read, so this costs one header read per playlist track, not per file.

**The length comparison is deliberately loose.** `NEUTRAL_VERSION_WORDS` makes
an extended mix and a radio edit the same track, and that does not change
here: a 7-minute extended mix against Spotify's 3:30 radio edit is owned. Only
a difference no edit explains is a mismatch: at least `LONGER_RATIO` times as
long *and* `LONGER_SECONDS` longer, or at most `SHORTER_RATIO` of the length.

**Every threshold was checked against the reference library** (3,664 files):

- `CUT_OFF_RATIO`: file size over the bytes its header's bitrate and length
  imply. Every healthy file is at 1.000 or above (MP3 3,648, FLAC 7, WAV 8;
  tags and cover art only add bytes). Below 0.95 sit exactly two files, both
  confirmed damaged by `sdm quality`'s decode: an MP3 at 0.867 that claims
  8:05 and holds 7:00, and an AIFF at 0.479 that does not decode at all. A
  file whose header is consistent with its size (a VBR MP3 without a Xing
  header, whose length mutagen derives from the size) cannot fail this, which
  is the safe direction.
- `MIN_TRACK_SECONDS`, used only when the playlist gives no length: the 15
  files under 30 s are samples and sound bites (1.5-13 s), and a Spotify
  preview clip is 30 s.
- `LONGER_*`: the longest real tracks are 12-13.5 minutes; the files beyond
  that are mixes (19-122 minutes). Versions of one song in the library differ
  by at most 1.46x.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from sdm.core.tags import read_audio_header

#: Below this, the file holds less audio than its header says: cut off or damaged.
CUT_OFF_RATIO = 0.95

#: A file this many times Spotify's length *and* this much longer is not the track.
LONGER_RATIO = 2.0
LONGER_SECONDS = 10 * 60

#: A file this fraction of Spotify's length or less is not the track. An edit is
#: rarely under half the original; a preview clip of a 3-minute song is 0.17.
SHORTER_RATIO = 0.3

#: With no length from the playlist, a file shorter than this is not a song.
MIN_TRACK_SECONDS = 35


@dataclass(frozen=True)
class FileFacts:
    """The little a header says that decides whether a file can be the track."""
    duration_seconds: Optional[float]
    problem: Optional[str]  # what is wrong with the file whatever track it is matched to


def inspect(path: str) -> FileFacts:
    """Read `path`'s header once. Never raises."""
    header = read_audio_header(path)
    if header.error:
        return FileFacts(None, f"unreadable ({header.error})")
    duration = header.duration_seconds
    if not duration:
        return FileFacts(None, "holds no audio")
    if header.bitrate_kbps:
        try:
            size = os.path.getsize(path)
        except OSError as e:
            return FileFacts(duration, f"unreadable ({e.strerror or e})")
        ratio = size / (header.bitrate_kbps * 125 * duration)
        if ratio < CUT_OFF_RATIO:
            return FileFacts(duration, f"cut off or damaged: holds about {clock(duration * ratio)} "
                                       f"of the {clock(duration)} its header claims")
    return FileFacts(duration, None)


def verdict(facts: FileFacts, expected_ms: Optional[int]) -> Optional[str]:
    """Why this file is not the playlist track of length `expected_ms`, or None if it can be."""
    if facts.problem:
        return facts.problem
    have = facts.duration_seconds
    if not expected_ms:
        if have < MIN_TRACK_SECONDS:
            return f"too short to be a song ({clock(have)}): a preview clip or a cut-off file?"
        return None
    want = expected_ms / 1000
    if have >= want * LONGER_RATIO and have - want >= LONGER_SECONDS:
        return f"far too long ({clock(have)}, Spotify's track is {clock(want)}): a mix or a podcast under this name?"
    if have <= want * SHORTER_RATIO:
        return f"far too short ({clock(have)}, Spotify's track is {clock(want)}): a preview clip or a cut-off file?"
    return None


def clock(seconds: Optional[float]) -> str:
    """6:05, or 1:02:13 past an hour. Empty for None."""
    if seconds is None:
        return ""
    total = round(seconds)
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"
