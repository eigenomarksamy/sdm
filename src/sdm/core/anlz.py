"""Rekordbox's own analysis, read off a Pioneer USB.

A Rekordbox export carries far more than a track list. Beside every track, under
`PIONEER/USBANLZ/P<nnn>/<hash>/`, Rekordbox writes an analysis file set —
`ANLZ0000.DAT`, `.EXT` and `.2EX` — holding the beat grid it computed, the
phrase structure it detected, and several waveform renderings. None of that is
in the audio file's tags, and none of it is in the exported database, so this is
the only way to reach it without the desktop application.

Two things make this a module rather than a call straight into pyrekordbox:

**Cost.** `AnlzFile.parse_file` parses every tag, and waveforms are almost all
of the bytes — a `.2EX` is ~220KB of waveform against ~2KB of phrase data.
Parsing the reference library that way takes 8m28s; parsing only the tags in
`ANALYSIS_TAGS` takes 38s. `WAVEFORM_TAGS` is named so the door stays open, but
nothing here asks for them yet.

**Tolerance.** pyrekordbox parses a file as one construct `Struct`, so a single
tag it disagrees with loses the whole file. Two disagreements are real on a
current library. `PQTZ` declares its second header word a constant `0x00080000`
when only the high half is fixed (119 of 3,665 files on the reference USB trip
it; 117 of those beat grids parse fine once the word is read as a number — see
`_beat_grid`). And newer Rekordbox versions emit `PVDI`/`PVB2` tags it has never
seen. Walking the tag chain here and parsing tags one at a time means a tag that
fails costs that tag and nothing else.

The binary layouts still come from `pyrekordbox.anlz`; this module never
re-describes them, it only chooses which to parse and survives the ones that
fail. `features/rekordbox/analysis.py` is the cautionary counter-example — it
hunted for `PSGL` and `PKEY` tags, neither of which exists in the format.

**What is not here, and why.** Musical key is not in ANLZ at all; Rekordbox
keeps it in the database, so `sdm rekordbox` remains the only source for it.
Cue points are in the format (`PCOB`/`PCO2`) and are deliberately not parsed:
the reference library of 3,665 tracks carries one hot cue and no memory cues, so
a cue reader would be untested code serving nothing. Add it when a library
actually has cues to read.
"""
from __future__ import annotations

import os
import struct
from dataclasses import dataclass
from typing import Any, Callable, Iterator, Optional, Sequence

#: Tags this module parses. `PPTH` names the track, `PQTZ` is the beat grid,
#: `PQT2` its extended form (whose header carries a track-level BPM, used when
#: `PQTZ` is missing), `PSSI` the phrase structure.
ANALYSIS_TAGS = ("PPTH", "PQTZ", "PQT2", "PSSI")

#: Parsed by nothing here. Listed because they are the reason the selective
#: parse exists, and the place to start if waveform output is ever wanted.
WAVEFORM_TAGS = ("PWAV", "PWV2", "PWV3", "PWV4", "PWV5", "PWV6", "PWV7", "PWVC")

#: Where a Rekordbox export keeps its analysis files, relative to the USB root.
USBANLZ_SUBDIR = os.path.join("PIONEER", "USBANLZ")

#: Every ANLZ tag opens with these three fields, whatever its body. Reading just
#: this is what lets the chain be walked past a tag whose body will not parse.
_TAG_HEADER = struct.Struct(">4sII")

#: PSSI's `mood`, which selects how phrase kinds are named.
_MOODS = {1: "high", 2: "mid", 3: "low"}

#: Phrase names for the mid and low moods, which share a scheme. Confirmed
#: against the reference library: both moods use exactly kinds 1..10.
_MID_LOW_PHRASES = {
    1: "Intro",
    2: "Verse 1",
    3: "Verse 2",
    4: "Verse 3",
    5: "Verse 4",
    6: "Verse 5",
    7: "Verse 6",
    8: "Bridge",
    9: "Chorus",
    10: "Outro",
}

#: The high mood uses a smaller set of kinds and distinguishes variants with
#: separate flag fields — `k1` splits Intro/Chorus/Outro into a first and second
#: form, `k2`/`k3` pick which of the three Up phrases this is. The reference
#: library bears this out: high-mood tracks use only kinds {1, 2, 3, 5, 6}, and
#: `k1` appears only on 1/5/6 while `k2`/`k3` appear only on 2.
_HIGH_PHRASES = {1: "Intro", 3: "Down", 5: "Chorus", 6: "Outro"}


@dataclass(frozen=True)
class Beat:
    """One beat of the grid Rekordbox computed."""

    number: int      # 1..4, position within the bar; 1 is a downbeat
    tempo: float     # BPM in force at this beat
    time_ms: int     # offset from the start of the track


@dataclass(frozen=True)
class Phrase:
    """One phrase of the structure Rekordbox detected.

    `end_beat` is exclusive and comes from the next phrase's start, or from the
    tag's own end for the last one — PSSI records only where phrases begin.
    """

    index: int
    label: str                  # "Intro 1", "Up 2", "Chorus", "Verse 3", ...
    kind: int                   # the raw PSSI kind, kept so nothing is lost
    start_beat: int
    end_beat: Optional[int]
    start_ms: Optional[int]
    end_ms: Optional[int]
    fill_beat: Optional[int]    # where the ending fill-in starts, if there is one


@dataclass(frozen=True)
class TrackAnalysis:
    """Everything `ANALYSIS_TAGS` yielded for one track.

    `beats` is empty unless the read asked for it: a library-wide run holds
    thousands of tracks at roughly a thousand beats each, and the summary fields
    beside it are what callers actually report on.
    """

    anlz_dir: str
    device_path: str                # "/Contents/..." as Rekordbox recorded it
    file_path: Optional[str]        # resolved against the USB, None if absent
    bpm: Optional[float]
    tempo_is_variable: bool
    beat_count: int
    first_downbeat_ms: Optional[int]
    mood: Optional[str]
    phrases: "tuple[Phrase, ...]"
    beats: "tuple[Beat, ...]"
    warnings: "tuple[str, ...]"

    @property
    def intro_end_ms(self) -> Optional[int]:
        """Where the last Intro phrase gives way to the body of the track."""
        end = None
        for phrase in self.phrases:
            if phrase.label.startswith("Intro"):
                end = phrase.end_ms
            else:
                break
        return end

    @property
    def outro_start_ms(self) -> Optional[int]:
        """Where the first Outro phrase begins."""
        for phrase in self.phrases:
            if phrase.label.startswith("Outro"):
                return phrase.start_ms
        return None


def iter_anlz_sets(usb_path: str) -> "Iterator[tuple[str, dict[str, str]]]":
    """Yield `(set_id, {".DAT": path, ".EXT": path, ...})` for every track.

    `usb_path` may be the USB root or the `USBANLZ` directory itself, so a
    caller can point at either without knowing the layout.

    Sets are keyed by directory *and* file stem: a hash directory usually holds
    one `ANLZ0000.*` trio, but not always, and collapsing them would silently
    drop a track.
    """
    root = _usbanlz_root(usb_path)
    if not os.path.isdir(root):
        return

    for bank in sorted(os.listdir(root)):
        bank_dir = os.path.join(root, bank)
        if not os.path.isdir(bank_dir):
            continue
        for hash_name in sorted(os.listdir(bank_dir)):
            hash_dir = os.path.join(bank_dir, hash_name)
            if not os.path.isdir(hash_dir):
                continue

            sets: "dict[str, dict[str, str]]" = {}
            for filename in sorted(os.listdir(hash_dir)):
                stem, ext = os.path.splitext(filename)
                ext = ext.upper()
                if ext in (".DAT", ".EXT", ".2EX"):
                    sets.setdefault(stem, {})[ext] = os.path.join(hash_dir, filename)

            for stem in sorted(sets):
                yield os.path.join(bank, hash_name, stem), sets[stem]


def read_usb(
    usb_path: str,
    with_beats: bool = False,
    progress: Optional[Callable[[str], None]] = None,
) -> Iterator[TrackAnalysis]:
    """Yield a `TrackAnalysis` for every track analysed on the USB.

    A generator rather than a list: the full beat grid of a library is millions
    of objects, and a caller that writes rows as it goes never has to hold them.
    """
    root = _usbanlz_root(usb_path)
    device_root = os.path.dirname(os.path.dirname(root))

    for index, (set_id, files) in enumerate(iter_anlz_sets(usb_path), start=1):
        if progress and index % 250 == 0:
            progress(f"  read {index} track(s)")
        analysis = read_anlz_set(files, device_root=device_root, with_beats=with_beats)
        if analysis is not None:
            yield analysis


def read_anlz_set(
    files: "dict[str, str]",
    device_root: Optional[str] = None,
    with_beats: bool = False,
) -> Optional[TrackAnalysis]:
    """Parse one ANLZ file set into a `TrackAnalysis`.

    `.DAT` carries the beat grid, `.EXT` the phrase structure and the extended
    grid; both repeat the path. `.2EX` is waveform-only, so it is not opened.
    Returns None only if nothing at all could be read.
    """
    tags: "dict[str, list[Any]]" = {}
    warnings: "list[str]" = []

    for ext in (".DAT", ".EXT"):
        path = files.get(ext)
        if path is None:
            continue
        try:
            with open(path, "rb") as handle:
                data = handle.read()
        except OSError as exc:
            warnings.append(f"{ext}: unreadable ({exc.__class__.__name__})")
            continue
        _collect_tags(data, tags, warnings, ext)

    if not tags:
        return None

    device_path = _device_path(tags)
    beats = _beat_grid(tags)
    phrases = _phrases(tags, beats)

    tempos = {beat.tempo for beat in beats}
    bpm = _bpm(beats, tempos, tags)

    file_path = None
    if device_root and device_path:
        candidate = os.path.join(device_root, device_path.lstrip("/").replace("/", os.sep))
        if os.path.exists(candidate):
            file_path = os.path.normpath(candidate)
        else:
            warnings.append("audio file not found at the recorded path")

    anlz_dir = os.path.dirname(next(iter(files.values())))
    return TrackAnalysis(
        anlz_dir=anlz_dir,
        device_path=device_path or "",
        file_path=file_path,
        bpm=bpm,
        tempo_is_variable=len(tempos) > 1,
        beat_count=len(beats),
        first_downbeat_ms=_first_downbeat_ms(beats),
        mood=_MOODS.get(_mood_value(tags)),
        phrases=tuple(phrases),
        beats=tuple(beats) if with_beats else (),
        warnings=tuple(warnings),
    )


# -- tag chain ------------------------------------------------------------------------


def _collect_tags(
    data: bytes,
    tags: "dict[str, list[Any]]",
    warnings: "list[str]",
    ext: str,
) -> None:
    """Walk one file's tag chain, parsing only `ANALYSIS_TAGS`.

    The walk is driven by `_TAG_HEADER` alone, so a tag whose body pyrekordbox
    cannot parse — or has never heard of — costs that tag and nothing else; the
    chain steps over it by its declared length and carries on.
    """
    from pyrekordbox.anlz import structs

    try:
        header = structs.AnlzFileHeader.parse(data)
    except Exception as exc:
        warnings.append(f"{ext}: bad file header ({exc.__class__.__name__})")
        return

    offset = header.len_header
    end = min(header.len_file, len(data))

    while offset + _TAG_HEADER.size <= end:
        raw_type, _len_header, len_tag = _TAG_HEADER.unpack_from(data, offset)
        # A length that would not advance, or would run off the end, means the
        # chain is no longer trustworthy. Stop rather than resynchronize: what
        # has been read so far is still good.
        if len_tag < _TAG_HEADER.size or offset + len_tag > end:
            warnings.append(f"{ext}: tag chain truncated at byte {offset}")
            return

        tag_type = raw_type.decode("ascii", "replace")
        if tag_type in ANALYSIS_TAGS:
            body = data[offset:offset + len_tag]
            parsed = _parse_tag(tag_type, body, warnings, ext)
            if parsed is not None:
                tags.setdefault(tag_type, []).append(parsed)

        offset += len_tag


def _parse_tag(
    tag_type: str, body: bytes, warnings: "list[str]", ext: str
) -> Optional[Any]:
    """Parse one tag body, returning None (and noting it) if it will not parse."""
    from pyrekordbox.anlz import tags as anlz_tags

    if tag_type == "PSSI":
        body = _unmask_pssi(body)

    try:
        return anlz_tags.TAGS[tag_type](body).content
    except Exception as exc:
        if tag_type == "PQTZ":
            recovered = _relaxed_beat_grid(body)
            if recovered is not None:
                warnings.append("beat grid: recovered past a bad header constant")
                return recovered
        warnings.append(f"{ext}: {tag_type} did not parse ({exc.__class__.__name__})")
        return None


def _unmask_pssi(body: bytes) -> bytes:
    """Undo the XOR mask Rekordbox 6 applies to phrase data when exporting.

    Masked or not is decided the way pyrekordbox decides it: `mood` is 1, 2 or 3
    in the clear, so anything else means the body is masked. The reference USB
    turns out to be unmasked, which is why the phrase data was readable at all —
    but an export from a newer Rekordbox will be masked, and dropping this would
    turn that into silently garbled output rather than an obvious failure.
    """
    from construct import Int16ub
    from pyrekordbox.anlz.file import XOR_MASK

    if len(body) < 20:
        return body

    mood = Int16ub.parse(body[18:20])
    if 1 <= mood <= 3:
        return body

    entry_count = Int16ub.parse(body[16:18])
    unmasked = bytearray(body)
    for i in range(len(unmasked) - 18):
        unmasked[18 + i] ^= (XOR_MASK[i % len(XOR_MASK)] + entry_count) % 256
    return bytes(unmasked)


_relaxed_grid_struct = None


def _relaxed_beat_grid(body: bytes) -> Optional[Any]:
    """Re-parse a `PQTZ` body with its second header word read as a number.

    pyrekordbox declares that word `Const(0x00080000)`. On the reference USB 119
    of 3,665 files carry `0x0008xxxx` there instead — the high half is fixed, the
    low half is not — and pyrekordbox therefore throws away the whole `.DAT`,
    beat grid included. Read as a plain integer, 117 of those 119 produce grids
    that pass `_looks_like_a_grid` below.

    The two that still fail are left failing. This is a narrow workaround for one
    over-strict field, not a second parser: everything else about the tag,
    including the per-beat struct, still comes from pyrekordbox.
    """
    global _relaxed_grid_struct

    if _relaxed_grid_struct is None:
        from construct import Array, Int32ub, Padding, Struct, this
        from pyrekordbox.anlz import structs

        _relaxed_grid_struct = Struct(
            "u1" / Padding(4),
            "u2" / Int32ub,
            "entry_count" / Int32ub,
            "entries" / Array(this.entry_count, structs.AnlzQuantizeTick),
        )

    try:
        content = _relaxed_grid_struct.parse(body[_TAG_HEADER.size:])
    except Exception:
        return None

    return content if _looks_like_a_grid(content.entries) else None


def _looks_like_a_grid(entries: Sequence[Any]) -> bool:
    """Sanity-check a relaxed parse before trusting it.

    Relaxing a constant means giving up the check that the constant was there to
    perform, so the result has to earn its place: beats number 1..4 within the
    bar and times increase. Junk read at the wrong offset fails both.
    """
    if not entries:
        return False
    if any(not 1 <= entry.beat <= 4 for entry in entries):
        return False
    return all(
        entries[i].time <= entries[i + 1].time for i in range(len(entries) - 1)
    )


# -- derived values -------------------------------------------------------------------


def _device_path(tags: "dict[str, list[Any]]") -> Optional[str]:
    """The track's path as Rekordbox recorded it, from whichever file had one."""
    for content in tags.get("PPTH", ()):
        path = getattr(content, "path", None)
        if path:
            return path
    return None


def _beat_grid(tags: "dict[str, list[Any]]") -> "list[Beat]":
    """The beat grid, newest-format-first."""
    for content in tags.get("PQTZ", ()):
        entries = getattr(content, "entries", None)
        if entries:
            return [
                Beat(number=e.beat, tempo=e.tempo / 100.0, time_ms=e.time)
                for e in entries
            ]
    return []


def _bpm(
    beats: "list[Beat]", tempos: "set[float]", tags: "dict[str, list[Any]]"
) -> Optional[float]:
    """The track's tempo.

    Taken from the beat grid, which is Rekordbox's own analysis rather than
    anything a tag claims. Where the tempo varies the most common value wins, so
    a single ramped bar does not decide the number for the whole track. With no
    grid at all, `PQT2`'s header still carries one.
    """
    if tempos:
        if len(tempos) == 1:
            return next(iter(tempos))
        counts: "dict[float, int]" = {}
        for beat in beats:
            counts[beat.tempo] = counts.get(beat.tempo, 0) + 1
        return max(counts.items(), key=lambda item: item[1])[0]

    for content in tags.get("PQT2", ()):
        entries = getattr(content, "bpm", None)
        if entries:
            tempo = getattr(entries[0], "tempo", 0)
            if tempo:
                return tempo / 100.0
    return None


def _first_downbeat_ms(beats: "list[Beat]") -> Optional[int]:
    """When the first complete bar starts — the anchor for anything beat-aligned."""
    for beat in beats:
        if beat.number == 1:
            return beat.time_ms
    return None


def _mood_value(tags: "dict[str, list[Any]]") -> Optional[int]:
    for content in tags.get("PSSI", ()):
        return getattr(content, "mood", None)
    return None


def _phrases(tags: "dict[str, list[Any]]", beats: "list[Beat]") -> "list[Phrase]":
    """Turn PSSI entries into phrases with names and, where possible, times.

    PSSI records only where each phrase *starts*, as a beat number into the grid,
    so each phrase's end is the next one's start and the last one's end is the
    tag's own `end_beat`. Times come from the grid; without one the phrases are
    still returned, in beats alone.
    """
    contents = tags.get("PSSI", ())
    if not contents:
        return []

    content = contents[0]
    entries = list(getattr(content, "entries", ()))
    if not entries:
        return []

    entries.sort(key=lambda e: e.beat)
    mood = getattr(content, "mood", None)
    track_end_beat = getattr(content, "end_beat", None)

    def time_of(beat_number: Optional[int]) -> Optional[int]:
        if not beat_number or not beats:
            return None
        # PSSI beat numbers are 1-based indices into the grid.
        index = min(max(beat_number, 1), len(beats)) - 1
        return beats[index].time_ms

    phrases = []
    for position, entry in enumerate(entries):
        if position + 1 < len(entries):
            end_beat = entries[position + 1].beat
        else:
            end_beat = track_end_beat
        phrases.append(
            Phrase(
                index=getattr(entry, "index", position + 1),
                label=_phrase_label(mood, entry),
                kind=entry.kind,
                start_beat=entry.beat,
                end_beat=end_beat,
                start_ms=time_of(entry.beat),
                end_ms=time_of(end_beat),
                fill_beat=entry.beat_fill if getattr(entry, "fill", 0) else None,
            )
        )
    return phrases


def _phrase_label(mood: Optional[int], entry: Any) -> str:
    """Name a phrase, which takes the mood: the same `kind` means different things.

    Mid and low moods name phrases by `kind` alone. The high mood uses fewer
    kinds and carries the variant in separate flags — `k1` picks the second form
    of Intro, Chorus and Outro, and `k2`/`k3` pick which Up phrase this is. An
    unrecognized kind is reported rather than guessed at, so a format change
    shows up in the output instead of hiding behind a plausible name.
    """
    kind = entry.kind

    if mood == 1:
        if kind == 2:
            if getattr(entry, "k3", 0):
                return "Up 3"
            if getattr(entry, "k2", 0):
                return "Up 2"
            return "Up 1"
        name = _HIGH_PHRASES.get(kind)
        if name is None:
            return f"Unknown (high, kind {kind})"
        if name == "Down":
            return name
        return f"{name} {2 if getattr(entry, 'k1', 0) else 1}"

    if mood in (2, 3):
        name = _MID_LOW_PHRASES.get(kind)
        return name if name else f"Unknown (mood {mood}, kind {kind})"

    return f"Unknown (mood {mood}, kind {kind})"


def _usbanlz_root(usb_path: str) -> str:
    """Accept either the USB root or the `USBANLZ` directory itself."""
    if os.path.basename(os.path.normpath(usb_path)).upper() == "USBANLZ":
        return usb_path
    return os.path.join(usb_path, USBANLZ_SUBDIR)
