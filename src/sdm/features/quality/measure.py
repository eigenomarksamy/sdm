"""Measuring what a file's audio actually is.

One `ffprobe` call for the stream's layout, then a single `ffmpeg` decode that
does two jobs at once: its `ebur128` filter measures loudness and true peak on
the way through, and the decoded PCM is streamed into numpy for everything
ffmpeg does not report — clipping, the spectral cutoff, effective bit depth and
stereo correlation. One decode is the design; the decode is most of the cost.

`-v verbose` is load-bearing, not noise. At that level ffmpeg ends with a line
per input stream giving the bytes of audio it read and how many frames failed
to decode. Packet bytes over decoded duration is the file's true average
bitrate — tags, cover art and the Xing frame are not packets, so none of them
inflate it — and the decode-error count is corruption nobody would otherwise
see until it clicks in a set.

Every number here is a measurement of the audio, never a reading of a header.
What the header claims is `core.tags.read_audio_header`'s business; comparing
the two is `compare.py`'s.

Both tools run through `core.tools.run`: processes here, WebAssembly builds of
the same 7.1.1 in the browser build. The reads are the same size either way,
which keeps the spectrum, and so the report, the same.
"""
from __future__ import annotations

import json
import math
import re
import subprocess
import threading
from dataclasses import dataclass
from typing import Optional

import numpy as np

from sdm.core import tools

#: FFT length for the long-term spectrum: ~11 Hz bins at 44.1 kHz, fine enough
#: to place an encoder's lowpass to within a few bins.
FFT_SIZE = 4096

#: FFT frames decoded per read from ffmpeg. A read is then a whole number of
#: frames, so no samples have to be carried from one chunk to the next.
FRAMES_PER_READ = 64

#: Where the spectrum counts as empty, relative to the median level of
#: 1-8 kHz. The prototype run: honest 128 kbps mp3s sit at -5..-40 dB below
#: their 16-17 kHz lowpass and -85..-99 above it, a 320 drops from about -35
#: to -90 at 20 kHz, and a FLAC never went below -34 at all. -60 sits in the
#: gap with room either side.
CUTOFF_FLOOR_DB = -60.0

#: How far the level must fall across the cutoff — from 1 kHz below it to
#: 500 Hz above — for it to count as an encoder's lowpass rather than music
#: whose top octave is merely quiet. Lowpass cliffs measured 55-80 dB.
CLIFF_DB = 25.0

#: A sample at or beyond this counts as clipped: 32767/32768, the largest
#: positive 16-bit value, so a 16-bit file pinned at full scale counts. A lossy
#: decode can go further, past 1.0, and those overs clip on any fixed-point
#: playback path — a CDJ's included.
FULL_SCALE = 1.0 - 2.0 ** -15

#: Codecs whose decoded samples are the stored samples, so "how many bits are
#: actually used" is a question with an answer.
_LOSSLESS_CODECS = ("flac", "alac", "wavpack", "ape", "tta")


@dataclass(frozen=True)
class Measurement:
    """The audio as decoded. None for anything that could not be measured."""
    codec: Optional[str] = None
    sample_rate: Optional[int] = None
    channels: Optional[int] = None
    stored_bit_depth: Optional[int] = None    # bits per sample the lossless stream stores
    bit_depth: Optional[int] = None           # bits actually used; integer lossless streams only
    duration_seconds: Optional[float] = None  # decoded samples over the rate, not a header's figure
    bitrate_kbps: Optional[float] = None      # audio packet bytes over that duration
    decode_errors: Optional[int] = None
    cutoff_hz: Optional[float] = None         # highest frequency with content; None when it reaches the top
    cutoff_sharp: bool = False                # the cutoff is a cliff, i.e. a lowpass, not a roll-off
    integrated_lufs: Optional[float] = None
    loudness_range_lu: Optional[float] = None
    true_peak_dbtp: Optional[float] = None
    sample_peak_dbfs: Optional[float] = None
    clipped_samples: Optional[int] = None
    total_samples: Optional[int] = None       # per channel times channels, i.e. what was counted
    stereo_correlation: Optional[float] = None
    error: Optional[str] = None


def is_lossless(codec: Optional[str]) -> bool:
    return bool(codec) and (codec in _LOSSLESS_CODECS or codec.startswith("pcm_"))


def measure(path: str, decoders: Optional[Decoders] = None) -> Measurement:
    """Decode `path` once and measure it.

    A file that fails to probe or decode comes back with `error` set rather
    than raising. A missing ffmpeg or ffprobe binary *does* raise
    (`RuntimeError`): that is not this file's fault, and the caller should stop
    the run instead of recording the same error for every track. So does a
    stopped `decoders` (`Cancelled`).
    """
    decoders = decoders or Decoders()
    try:
        stream = _probe(path, decoders)
    except _FileError as e:
        return Measurement(error=str(e))

    codec = stream.get("codec_name")
    sample_rate = _int(stream.get("sample_rate"))
    channels = _int(stream.get("channels"))
    if not sample_rate or not channels:
        return Measurement(codec=codec, error="ffprobe reported no sample rate or channel count")

    declared_bits = _int(stream.get("bits_per_raw_sample")) or _int(stream.get("bits_per_sample"))
    # float32 holds a 24-bit integer exactly, and no more, so 32-bit integer
    # and float sources have no effective depth this can find.
    count_bits = is_lossless(codec) and declared_bits is not None and declared_bits <= 24 \
        and "f" not in (stream.get("sample_fmt") or "")

    acc = _Accumulator(channels, count_bits)
    stderr = _decode(path, channels, acc, decoders)
    decode_errors = _search_int(r"(\d+) decode errors", stderr)

    frames = acc.frames
    if not frames:
        # ebur128 still prints a summary over no audio, with a 0.0 dB peak that
        # is no measurement at all, so nothing is kept but the failure.
        return Measurement(codec=codec, sample_rate=sample_rate, channels=channels,
                           decode_errors=decode_errors, error=_failure(stderr))

    duration = frames / sample_rate
    packet_bytes = _search_int(r"\(audio\): \d+ packets read \((\d+) bytes\)", stderr)
    loudness = _ebur128(stderr)
    cutoff_hz, sharp = find_cutoff(acc.spectrum(), sample_rate) if acc.ffts else (None, False)

    return Measurement(
        codec=codec,
        sample_rate=sample_rate,
        channels=channels,
        stored_bit_depth=declared_bits if is_lossless(codec) else None,
        bit_depth=acc.bit_depth() if count_bits else None,
        duration_seconds=duration,
        bitrate_kbps=packet_bytes * 8 / duration / 1000 if packet_bytes else None,
        decode_errors=decode_errors,
        cutoff_hz=cutoff_hz,
        cutoff_sharp=sharp,
        integrated_lufs=loudness.get("I"),
        loudness_range_lu=loudness.get("LRA"),
        true_peak_dbtp=loudness.get("TP"),
        sample_peak_dbfs=_db(acc.peak),
        clipped_samples=acc.clipped,
        total_samples=frames * channels,
        stereo_correlation=acc.correlation(),
    )


def find_cutoff(power: np.ndarray, sample_rate: int) -> tuple[Optional[float], bool]:
    """The highest frequency with content, and whether the spectrum ends in a cliff.

    `power` is the mean power per FFT bin. Levels are taken relative to the
    median of 1-8 kHz, where every kind of music has energy, so a quiet track
    and a loud one are judged alike. The cutoff is the highest frequency still
    above `CUTOFF_FLOOR_DB`; (None, False) means content runs to within 2% of
    Nyquist, i.e. there is no cutoff to report.

    *Sharp* separates an encoder's lowpass — content, then nothing, within a few
    hundred hertz — from a recording whose top octave just fades. Only a sharp
    cutoff is evidence of anything.
    """
    freqs = np.fft.rfftfreq(FFT_SIZE, 1.0 / sample_rate)
    level = 10.0 * np.log10(power + 1e-30)
    band = (freqs >= 1000) & (freqs <= 8000)
    if not band.any():
        return None, False
    rel = level - np.median(level[band])

    bin_hz = sample_rate / FFT_SIZE
    # ~200 Hz of smoothing, so no single noisy bin decides the edge. Padded
    # with the edge values, not zeros: zero padding averages 0 dB into the top
    # bins, which lifted every lossy file's -90 dB floor over the threshold at
    # Nyquist and made it look full-band.
    width = max(1, int(round(200 / bin_hz)))
    pad = width // 2
    rel = np.convolve(np.pad(rel, (pad, width - 1 - pad), mode="edge"),
                      np.ones(width) / width, mode="valid")

    above = np.nonzero(rel > CUTOFF_FLOOR_DB)[0]
    if not above.size:
        return None, False
    edge = int(above[-1])
    nyquist = sample_rate / 2
    if freqs[edge] >= 0.98 * nyquist:
        return None, False

    below_bins = int(round(1000 / bin_hz))
    above_bins = int(round(500 / bin_hz))
    before = rel[max(0, edge - below_bins): max(1, edge - below_bins // 2)].mean()
    after = rel[edge + 1: edge + 1 + above_bins]
    sharp = bool(after.size) and before - after.mean() >= CLIFF_DB
    return float(freqs[edge]), sharp


class Decoders:
    """Every ffprobe and ffmpeg process a run has in flight, so a cancel can stop them.

    A Ctrl-C (or `sdm web`'s cancel, the same signal) reaches the decoders
    running at that moment. It does not reach the ones worker threads start in
    the instant before the main thread notices, from files already queued, and
    each of those would decode a whole track before the run could end: a cancel
    measured 9.7 s before these were tracked. `stop` kills whatever is running
    and refuses to start more. Killing is safe here, unlike for the Python
    process itself: these only read.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._running: set[subprocess.Popen] = set()
        self._stopped = False

    def start(self, command: list[str], **kwargs) -> subprocess.Popen:
        with self._lock:
            if self._stopped:
                raise Cancelled()
            proc = subprocess.Popen(command, **kwargs)
            self._running.add(proc)
            return proc

    def finished(self, proc: subprocess.Popen) -> None:
        with self._lock:
            self._running.discard(proc)

    def stop(self) -> None:
        with self._lock:
            self._stopped = True
            for proc in self._running:
                if proc.poll() is None:
                    proc.kill()


class Cancelled(Exception):
    """The run was stopped; this file was not measured."""


class _FileError(Exception):
    """This file cannot be measured; the message says why."""


class _Accumulator:
    """Running sums over the decoded PCM, so no track is ever held whole in memory."""

    def __init__(self, channels: int, count_bits: bool) -> None:
        self.channels = channels
        self.count_bits = count_bits
        self.frames = 0
        self.peak = 0.0
        self.clipped = 0
        self.bits_or = 0
        self.ll = self.rr = self.lr = 0.0
        self.power = np.zeros(FFT_SIZE // 2 + 1)
        self.ffts = 0
        self.window = np.hanning(FFT_SIZE).astype(np.float32)

    def add(self, samples: np.ndarray) -> None:
        ch = self.channels
        frames = samples.reshape(-1, ch)
        self.frames += frames.shape[0]

        magnitude = np.abs(samples)
        self.peak = max(self.peak, float(magnitude.max()))
        self.clipped += int(np.count_nonzero(magnitude >= FULL_SCALE))

        if self.count_bits:
            # Exact: a <=24-bit integer sample scaled into float32 survives the
            # round trip, so OR-ing them shows the lowest bit any sample uses.
            q = np.rint(samples * 8388608.0).astype(np.int32)
            self.bits_or |= int(np.bitwise_or.reduce(q))

        if ch == 2:
            left = frames[:, 0].astype(np.float64)
            right = frames[:, 1].astype(np.float64)
            self.ll += float(left @ left)
            self.rr += float(right @ right)
            self.lr += float(left @ right)

        count = frames.shape[0] // FFT_SIZE
        if count:
            for c in range(ch):
                seg = frames[: count * FFT_SIZE, c].reshape(count, FFT_SIZE) * self.window
                spectrum = np.fft.rfft(seg, axis=1)
                self.power += (spectrum.real ** 2 + spectrum.imag ** 2).sum(axis=0)
            self.ffts += count * ch

    def spectrum(self) -> np.ndarray:
        return self.power / self.ffts

    def bit_depth(self) -> Optional[int]:
        if not self.bits_or:
            return None  # digital silence uses no bits at all
        lowest = (self.bits_or & -self.bits_or).bit_length() - 1
        return 24 - lowest

    def correlation(self) -> Optional[float]:
        if self.channels != 2 or not self.ll or not self.rr:
            return None
        return self.lr / math.sqrt(self.ll * self.rr)


def _probe(path: str, decoders: Decoders) -> dict:
    command = [
        "ffprobe", "-v", "error", "-select_streams", "a:0",
        "-show_entries",
        "stream=codec_name,sample_rate,channels,sample_fmt,bits_per_raw_sample,bits_per_sample",
        "-of", "json", path,
    ]
    try:
        completed = tools.run(command, tracker=decoders)
    except FileNotFoundError:
        raise RuntimeError("ffprobe not found. Install ffmpeg and put it on PATH.") from None
    out, err = completed.stdout, completed.stderr
    try:
        streams = json.loads(out.decode("utf-8", errors="replace") or "{}").get("streams")
    except ValueError:
        streams = None
    if not streams:
        message = err.decode("utf-8", errors="replace").strip()
        raise _FileError(message.splitlines()[-1] if message else "no audio stream")
    return streams[0]


def _decode(path: str, channels: int, acc: _Accumulator, decoders: Decoders) -> str:
    """Run the one decode, feeding `acc`; return ffmpeg's stderr."""
    command = [
        "ffmpeg", "-nostdin", "-hide_banner", "-nostats", "-v", "verbose",
        "-i", path, "-map", "0:a:0",
        "-af", "ebur128=peak=true:framelog=quiet",
        "-f", "f32le", "-",
    ]
    frame_bytes = 4 * channels

    def feed(data: bytes) -> None:
        usable = len(data) - len(data) % frame_bytes
        if usable:
            acc.add(np.frombuffer(data[:usable], dtype="<f4"))

    try:
        completed = tools.run(command, on_stdout=feed, tracker=decoders,
                               chunk_size=FFT_SIZE * FRAMES_PER_READ * frame_bytes)
    except FileNotFoundError:
        raise RuntimeError("ffmpeg not found. Install it and put it on PATH.") from None
    return completed.stderr.decode("utf-8", errors="replace")


def _ebur128(stderr: str) -> dict:
    """Integrated loudness, loudness range and true peak from ebur128's summary."""
    summary = stderr[stderr.rfind("Summary:"):] if "Summary:" in stderr else ""
    values = {}
    for key, pattern in (
        ("I", r"I:\s+(-?inf|-?\d+(?:\.\d+)?) LUFS"),
        ("LRA", r"LRA:\s+(-?\d+(?:\.\d+)?) LU\b"),
        ("TP", r"True peak:\s+Peak:\s+(-?inf|-?\d+(?:\.\d+)?) dBFS"),
    ):
        match = re.search(pattern, summary)
        if match and "inf" not in match.group(1):
            values[key] = float(match.group(1))
    # -70 LUFS is the absolute gate: what ebur128 reports for digital silence.
    if values.get("I", 0.0) <= -70.0:
        values.pop("I", None)
        values.pop("LRA", None)
    return values


def _failure(stderr: str) -> str:
    """The line of ffmpeg's output that says why nothing decoded.

    Not simply the last line: at `-v verbose` that is the closing statistics,
    the same for every failure. And ffmpeg does not always say: a file whose
    container ends before its audio starts — the reference USB has an AIFF whose
    FORM header claims 1,118 bytes of a 48 MB file — demuxes zero packets with
    no error at all.
    """
    for line in reversed(stderr.splitlines()):
        # The statistics line itself says "0 decode errors"; it is not the cause.
        if ("rror" in line or "nvalid" in line) and "decode errors" not in line:
            return line.strip()
    return "ffmpeg decoded no audio from this file; it may be damaged or truncated"


def _search_int(pattern: str, text: str) -> Optional[int]:
    match = re.search(pattern, text)
    return int(match.group(1)) if match else None


def _int(value) -> Optional[int]:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _db(amplitude: float) -> Optional[float]:
    return 20.0 * math.log10(amplitude) if amplitude > 0 else None
