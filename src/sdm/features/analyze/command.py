"""Runs the `sdm analyze` subcommand.

Walk the USB's analysis files -> report. All of the format knowledge is in
`sdm.core.anlz`; what lives here is the shape of the output and the decision to
stream it.

Streaming is the one design choice worth stating. A library's beat grids are
millions of `Beat` objects, so rows are written as tracks are read rather than
collected first — which is also why `--export-beats` costs nothing but disk, and
why the JSON report is built from summaries rather than from everything read.
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from collections import Counter
from typing import Optional

from sdm.core.anlz import TrackAnalysis, read_usb
from sdm.core.paths import out_dir
from sdm.core.report import ensure_dir, write_json
from sdm.core.tags import read_title_artist

_TRACK_HEADER = (
    "title",
    "artist",
    "device_path",
    "file_path",
    "file_found",
    "bpm",
    "tempo_is_variable",
    "beat_count",
    "first_downbeat_ms",
    "mood",
    "phrase_count",
    "intro_end_ms",
    "outro_start_ms",
    "warnings",
)

_PHRASE_HEADER = (
    "device_path",
    "phrase_index",
    "label",
    "kind",
    "start_beat",
    "end_beat",
    "bars",
    "start_ms",
    "end_ms",
    "fill_beat",
)

_BEAT_HEADER = ("device_path", "beat_index", "beat_in_bar", "tempo", "time_ms")


def run(args: argparse.Namespace) -> int:
    usb_path = args.usb_path
    if not os.path.isdir(usb_path):
        print(f"error: not a directory: {usb_path}", file=sys.stderr)
        return 2

    report_dir = ensure_dir(args.output_dir) if args.output_dir else out_dir("analyze")
    print(f"reading analysis from {usb_path}")

    tracks: "list[dict]" = []
    moods: "Counter[str]" = Counter()
    labels: "Counter[str]" = Counter()
    with_grid = with_phrases = warned = 0

    track_csv = os.path.join(report_dir, "analysis.csv")
    phrase_csv = os.path.join(report_dir, "phrases.csv")
    beat_csv = os.path.join(report_dir, "beats.csv")

    # newline="" for the same reason core.report opens files that way: without
    # it the csv module writes a blank line between rows on Windows.
    with open(track_csv, "w", newline="", encoding="utf-8") as track_file, \
            open(phrase_csv, "w", newline="", encoding="utf-8") as phrase_file:
        track_writer = csv.writer(track_file)
        phrase_writer = csv.writer(phrase_file)
        track_writer.writerow(_TRACK_HEADER)
        phrase_writer.writerow(_PHRASE_HEADER)

        beat_file = None
        beat_writer = None
        if args.export_beats:
            beat_file = open(beat_csv, "w", newline="", encoding="utf-8")
            beat_writer = csv.writer(beat_file)
            beat_writer.writerow(_BEAT_HEADER)

        try:
            for count, track in enumerate(
                read_usb(usb_path, with_beats=args.export_beats,
                         progress=lambda msg: print(msg)),
                start=1,
            ):
                # ANLZ records a path, never a name, so the title and artist
                # come from the audio file's own tags. Only for tracks whose
                # file actually resolved - there is nothing to read otherwise.
                title, artist = (
                    read_title_artist(track.file_path)
                    if track.file_path else ("Unknown", "Unknown")
                )

                track_writer.writerow(_track_row(track, title, artist))
                for phrase in track.phrases:
                    phrase_writer.writerow(_phrase_row(track, phrase))
                if beat_writer is not None:
                    for index, beat in enumerate(track.beats, start=1):
                        beat_writer.writerow(
                            [track.device_path, index, beat.number,
                             beat.tempo, beat.time_ms]
                        )

                tracks.append(_summary(track, title, artist))
                if track.beat_count:
                    with_grid += 1
                if track.phrases:
                    with_phrases += 1
                    labels.update(p.label for p in track.phrases)
                if track.mood:
                    moods[track.mood] += 1
                if track.warnings:
                    warned += 1

                if args.limit and count >= args.limit:
                    break
        finally:
            if beat_file is not None:
                beat_file.close()

    if not tracks:
        print("no analysis files found - is this a Rekordbox USB? "
              "(expected PIONEER/USBANLZ/ under it)", file=sys.stderr)
        return 1

    json_path = os.path.join(report_dir, "analysis.json")
    write_json(json_path, tracks)

    total = len(tracks)
    print(f"read {total} track(s)")
    print(f"  beat grid:       {with_grid} ({_pct(with_grid, total)})")
    print(f"  phrase structure: {with_phrases} ({_pct(with_phrases, total)})")
    if moods:
        print("  mood: " + ", ".join(f"{m} {n}" for m, n in moods.most_common()))
    if labels:
        top = ", ".join(f"{label} {n}" for label, n in labels.most_common(5))
        print(f"  most common phrases: {top}")
    if warned:
        print(f"  {warned} track(s) had at least one warning - see the report")

    print(f"wrote {track_csv}")
    print(f"wrote {phrase_csv}")
    if args.export_beats:
        print(f"wrote {beat_csv}")
    print(f"wrote {json_path}")
    return 0


def _track_row(track: TrackAnalysis, title: str, artist: str) -> list:
    return [
        title,
        artist,
        track.device_path,
        track.file_path or "",
        "yes" if track.file_path else "no",
        _round(track.bpm),
        "yes" if track.tempo_is_variable else "no",
        track.beat_count,
        _blank(track.first_downbeat_ms),
        track.mood or "",
        len(track.phrases),
        _blank(track.intro_end_ms),
        _blank(track.outro_start_ms),
        "; ".join(track.warnings),
    ]


def _phrase_row(track: TrackAnalysis, phrase) -> list:
    return [
        track.device_path,
        phrase.index,
        phrase.label,
        phrase.kind,
        phrase.start_beat,
        _blank(phrase.end_beat),
        _bars(phrase),
        _blank(phrase.start_ms),
        _blank(phrase.end_ms),
        _blank(phrase.fill_beat),
    ]


def _summary(track: TrackAnalysis, title: str, artist: str) -> dict:
    """The JSON shape: everything but the beat grid, which belongs in its own CSV."""
    return {
        "title": title,
        "artist": artist,
        "device_path": track.device_path,
        "file_path": track.file_path,
        "bpm": round(track.bpm, 2) if track.bpm is not None else None,
        "tempo_is_variable": track.tempo_is_variable,
        "beat_count": track.beat_count,
        "first_downbeat_ms": track.first_downbeat_ms,
        "mood": track.mood,
        "intro_end_ms": track.intro_end_ms,
        "outro_start_ms": track.outro_start_ms,
        "warnings": list(track.warnings),
        "phrases": [
            {
                "index": p.index,
                "label": p.label,
                "kind": p.kind,
                "start_beat": p.start_beat,
                "end_beat": p.end_beat,
                "bars": _bars(p),
                "start_ms": p.start_ms,
                "end_ms": p.end_ms,
                "fill_beat": p.fill_beat,
            }
            for p in track.phrases
        ],
    }


def _bars(phrase) -> Optional[int]:
    """Phrase length in bars - the unit a DJ counts in, where beats are not."""
    if phrase.end_beat is None:
        return None
    beats = phrase.end_beat - phrase.start_beat
    return beats // 4 if beats > 0 else 0


def _round(value: Optional[float]) -> str:
    return "" if value is None else f"{value:.2f}"


def _blank(value) -> object:
    return "" if value is None else value


def _pct(part: int, total: int) -> str:
    return f"{100.0 * part / total:.1f}%" if total else "0.0%"
