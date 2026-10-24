"""Decide which playlist tracks a folder already has, by title and artist.

Name matching, because nothing stronger is available on both sides: an ISRC
would settle it, but only 58 of the 3,664 files on the test clone carry one.

**Three outcomes, not two, and the middle one is the point.** A playlist track
is `owned` only when a file agrees on title, artist *and* version. When the
title and artist agree but the version does not (you have the original, the
playlist has a remix), or the title agrees but the file has no artist to
confirm it, the answer is `maybe`, reported alongside the missing tracks with
the file that nearly matched. A false "owned" is the expensive mistake — it
hides a track you will then never go and buy — so anything short of a clean
match stays visible.

A fourth, `mismatch`, comes from outside this module: a file that matches by
name but is not the track (a mix under its name, a preview clip, a damaged
file). The caller passes a `vet` that says so — see `checks.py` — and this
module only decides which candidate to believe.

How the two sides are reconciled:

- **Versions.** Spotify writes `Title - Extended Mix`, a Beatport-style tag
  writes `Title (Extended Mix)`; both are parsed into a base title plus version
  words. Words that name a release rather than a different recording
  (`NEUTRAL_VERSION_WORDS`: original, extended, radio edit, remastered 2011, …)
  are dropped. What is left — a remixer's name, "dub", "vip", "instrumental" —
  must agree exactly.
- **Artists.** Split into individual names on `/` `,` `;` `&` `x` `vs` `feat`,
  with the whole string kept too, and matched on any overlap. `/` is the one
  that matters most: it is how 304 artist tags on the test clone list several
  artists. Spotify lists remixers and featured artists as artists, a tag
  usually puts them in the title; overlap tolerates both.
- **Files with poor tags.** Each file is read several ways — its tags, the
  "Artist - Title" a YouTube rip leaves in the title tag, and its filename with
  rip-site junk stripped — and any reading can match. A wrong reading costs
  nothing, because it has to agree on title *and* artist with a playlist track.

The same normalization runs on both sides, so a quirk of it (splitting AC/DC
into "ac" and "dc") lands identically on each and cancels out.

Feature-local for now. `dig` will need the same "is this already owned"
question answered; per rule 1 this moves to `core` when it does, it is not
imported across.
"""
from __future__ import annotations

import os
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from typing import Callable, Iterable, Optional

#: Version words that name a release of a recording, not a different recording.
#: "Title (Extended Mix)" and "Title - Radio Edit" are the same track for the
#: question "do I have this"; "Title (Solomun Remix)" is not, and keeps
#: "solomun" and "remix" after these are removed. Four-digit years are dropped
#: separately, for "Remastered 2011".
NEUTRAL_VERSION_WORDS = frozenset({
    "original", "mix", "extended", "radio", "edit", "club", "version", "album",
    "single", "remaster", "remastered", "mono", "stereo", "explicit", "clean",
    "bonus", "track", "digital", "mixed", "12", "inch", "full", "length", "main",
    "lp",
})

#: Artist tags that name no one. A track "by" one of these cannot confirm a match.
PLACEHOLDER_ARTISTS = frozenset({"unknown", "unknown artist", "various artists", "various", "va"})

_FEAT_BRACKET = re.compile(r"[\(\[]\s*(?:feat|ft|featuring)\b\.?[^\)\]]*[\)\]]", re.IGNORECASE)
_FEAT_TAIL = re.compile(r"\s(?:feat|ft|featuring)\b\.?\s.*$", re.IGNORECASE)
_TRAILING_GROUP = re.compile(r"\s*[\(\[]([^\(\)\[\]]*)[\)\]]\s*$")
# "(Pt. 2)" names a different track, not a version of the same one: kept in the
# base title, so "Song (Pt. 2)" meets Spotify's "Song, Pt. 2".
_PART_GROUP = re.compile(r"(?:pt|part|vol|volume)\.?\s*\w+", re.IGNORECASE)
_DASH = re.compile(r"\s+[-–—]\s+")
_YEAR = re.compile(r"(?:19|20)\d{2}")
_ARTIST_SEP = re.compile(
    r"\s*(?:[,;/&+]|\bx\b|\bvs\b\.?|\bfeat\b\.?|\bft\b\.?|\bfeaturing\b)\s*", re.IGNORECASE
)

# Filename and title debris from rip sites and download tools.
_JUNK_PREFIX = re.compile(
    r"^(?:\s*\[[^\]]*\]\s*(?:[-–—]\s*)?"
    r"|\s*[\w-]+(?:\.[\w-]+)*\.(?:com|net|org|info|to|cc|me|io|ru|fm)\s*[-–—]\s*)+",
    re.IGNORECASE,
)
_TRACK_NUMBER = re.compile(r"^\s*\d{1,3}\s*[.)_-]\s+")
_JUNK_SUFFIX = re.compile(
    r"\s*[\(\[](?:\d{2,3}\s*kbps|official(?:\s+music)?\s+(?:video|audio)|lyrics?(?:\s+video)?"
    r"|hq|hd|audio)[\)\]]\s*$",
    re.IGNORECASE,
)
# A filename truncated mid-bracket, as YouTube rippers leave them: "Secret Fire (3".
_UNCLOSED = re.compile(r"\s*[\(\[][^\(\)\[\]]*$")


def fold(text: str) -> str:
    """Accent-strip, casefold, `&` -> "and", punctuation to spaces. The comparison form."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.casefold().replace("&", " and ")
    text = re.sub(r"['’`´]", "", text)  # "don't" -> "dont", not "don t"
    text = re.sub(r"[\W_]+", " ", text)
    return text.strip()


def parse_title(title: str) -> tuple[str, frozenset[str]]:
    """Split a title into `(base, version_words)`, both folded.

    "Cinema (feat. Gary Go) - Skrillex Remix" -> ("cinema", {"skrillex", "remix"});
    "Acid Carousel (Original Mix)" -> ("acid carousel", {}). Only *trailing*
    brackets are versions, so "(I Can't Get No) Satisfaction" keeps its own.
    """
    text = unicodedata.normalize("NFKC", title or "")
    text = _FEAT_BRACKET.sub(" ", text)

    versions: list[str] = []
    while True:
        match = _TRAILING_GROUP.search(text)
        if match is None or not text[: match.start()].strip():
            break
        if _PART_GROUP.fullmatch(match.group(1).strip()):
            break
        versions.append(match.group(1))
        text = text[: match.start()]

    parts = _DASH.split(text, maxsplit=1)
    base = _FEAT_TAIL.sub("", parts[0])
    if len(parts) == 2:
        versions.append(parts[1])

    words = set()
    for version in versions:
        for word in fold(_FEAT_TAIL.sub("", " " + version)).split():
            if word not in NEUTRAL_VERSION_WORDS and not _YEAR.fullmatch(word):
                words.add(word)
    return fold(base) or fold(title or ""), frozenset(words)


def artist_keys(names: Iterable[Optional[str]]) -> frozenset[str]:
    """Every name an artist string could mean: the whole of it, and each part of a list."""
    keys = set()
    for name in names:
        if not name:
            continue
        for candidate in [name, *_ARTIST_SEP.split(name)]:
            key = fold(candidate)
            if key.startswith("the "):
                key = key[4:]
            if key and key not in PLACEHOLDER_ARTISTS:
                keys.add(key)
    return frozenset(keys)


def _clean(text: str) -> str:
    """Strip rip-site prefixes, track numbers, "(320kbps)"-style suffixes and a truncated bracket."""
    text = _JUNK_PREFIX.sub("", text)
    text = _TRACK_NUMBER.sub("", text)
    text = _UNCLOSED.sub("", text)
    previous = None
    while previous != text:
        previous = text
        text = _JUNK_SUFFIX.sub("", text)
    return text.strip()


@dataclass(frozen=True)
class LocalTrack:
    path: str
    title: Optional[str]
    artist: Optional[str]

    @property
    def label(self) -> str:
        """How to name this file to a person: its tags when it has them, else its filename."""
        if self.title and self.title.strip():
            return f"{self.artist} - {self.title}" if self.artist and self.artist.strip() else self.title
        return os.path.basename(self.path)


@dataclass(frozen=True)
class _Reading:
    """One interpretation of a local file as (artist, title)."""
    track: LocalTrack
    base: str
    versions: frozenset[str]
    artists: frozenset[str]  # empty: the reading names no artist
    via: str


def _reading(track: LocalTrack, title: str, artist: Optional[str], via: str) -> _Reading:
    base, versions = parse_title(title)
    return _Reading(track, base, versions, artist_keys([artist]), via)


def _readings(track: LocalTrack) -> list[_Reading]:
    """Every plausible (artist, title) reading of one file. See the module docstring."""
    title = _clean(track.title) if track.title and track.title.strip() else ""
    artist = track.artist if track.artist and track.artist.strip() else None
    stem = _clean(os.path.splitext(os.path.basename(track.path))[0])

    readings = []
    if title:
        readings.append(_reading(track, title, artist, "tags"))
        halves = _DASH.split(title, maxsplit=1)
        if len(halves) == 2:
            readings.append(_reading(track, halves[1], halves[0], "artist in title tag"))
    else:
        readings.append(_reading(track, stem, artist, "filename"))
    halves = _DASH.split(stem, maxsplit=1)
    if len(halves) == 2:
        readings.append(_reading(track, halves[1], halves[0], "filename"))
    return [r for r in readings if r.base]


@dataclass(frozen=True)
class Match:
    status: str                  # "owned", "maybe", "mismatch" or "missing"
    local: Optional[LocalTrack]  # the file that matched or nearly matched
    via: str = ""                # which reading of that file matched
    note: str = ""               # for "maybe" and "mismatch": why it is not "owned"


#: Why a file that matched by name is not the track, or None if it can be. See `checks.py`.
Vet = Callable[[LocalTrack], Optional[str]]


class LocalIndex:
    """The folder's files, indexed by base title so a lookup is one dict hit."""

    def __init__(self, tracks: Iterable[LocalTrack]):
        self._by_base: dict[str, list[_Reading]] = defaultdict(list)
        for track in tracks:
            for reading in _readings(track):
                self._by_base[reading.base].append(reading)

    def match(self, title: str, artists: Iterable[str], vet: Optional[Vet] = None) -> Match:
        """The best file for a playlist track. `vet` rules out files that only share its name.

        Every file that matches by name is a candidate, and the first that
        passes `vet` in each tier wins, so a mix saved under a track's name does
        not hide the real file beside it. Only when every candidate fails is the
        answer `mismatch`, naming the first that failed.
        """
        base, versions = parse_title(title)
        wanted = artist_keys(artists)

        exact: list[_Reading] = []
        other_version: list[_Reading] = []
        unconfirmed: list[_Reading] = []
        for reading in self._by_base.get(base, ()):
            if not reading.artists or not wanted:
                unconfirmed.append(reading)
            elif reading.artists & wanted:
                (exact if reading.versions == versions else other_version).append(reading)
            # A same-titled file by someone else is a different song: no match.

        rejected: list[tuple[_Reading, str]] = []

        def first_sound(readings: list[_Reading]) -> Optional[_Reading]:
            for reading in readings:
                problem = vet(reading.track) if vet else None
                if problem is None:
                    return reading
                if all(r.track != reading.track for r, _ in rejected):
                    rejected.append((reading, problem))
            return None

        found = first_sound(exact)
        if found is not None:
            return Match("owned", found.track, found.via)
        # A rejected exact match is worth a mention beside a "maybe": it is why
        # the track is not simply owned.
        also = "".join(f"; also '{r.track.label}': {problem}" for r, problem in rejected)

        found = first_sound(other_version)
        if found is not None:
            return Match("maybe", found.track, found.via,
                         f"different version: have '{found.track.label}'{also}")
        found = first_sound(unconfirmed)
        if found is not None:
            return Match("maybe", found.track, found.via,
                         f"title matches, no artist to confirm: '{found.track.label}'{also}")
        if rejected:
            reading, problem = rejected[0]
            return Match("mismatch", reading.track, reading.via, problem)
        return Match("missing", None)
