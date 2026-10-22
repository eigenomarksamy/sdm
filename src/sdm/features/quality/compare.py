"""Where a file's audio disagrees with its metadata, or has a problem of its own.

`measure.py` says what the audio is, the header and Rekordbox say what it is
claimed to be; this decides which differences are worth a line in the report.
Each check yields a `Flag`: a kind to count by, and a sentence a person can
read without the columns beside it ("transcode? 16.1 kHz cutoff at 320 kbps").

A flag with a "?" is evidence, not a verdict. A spectral cutoff is what a
transcode leaves behind, and also what a few honest encoders and some lo-fi
masters produce; the row carries the numbers so the call is the reader's. That
is the same stance `playlist-diff` takes with "maybe": surface it, never
silently decide it.

The thresholds are named below because each is a judgment, and each was set
against the reference library rather than picked.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator, Optional

from sdm.core.rekordbox_db import RekordboxFile
from sdm.core.tags import AudioHeader
from sdm.features.quality.measure import Measurement, is_lossless

#: The lowest believable spectral cutoff for a lossy file of at least this
#: average bitrate. Measured on the reference library (3,648 mp3s): files
#: honestly encoded at 128 kbps cut at 16.1-16.9 kHz, at 192 at 18.8-19.1, at
#: 320 at 19.5 and up — LAME `-b 320` on a dark master included — with most
#: near 20-20.5. So 19.2 kHz sits between an honest 320 and one made from a
#: 192, and 17.5 between an honest 192 and one made from a 128.
LOSSY_CUTOFF_FLOORS = ((256, 19_200.0), (192, 17_500.0))

#: A lossless file whose spectrum ends in a cliff below this was, most likely,
#: decoded from a lossy one and saved again.
LOSSLESS_CUTOFF_FLOOR = 19_500.0

#: A file above 44.1 kHz whose content stops in a cliff below this was
#: resampled up from a lower rate: the cliff is the original's Nyquist.
UPSAMPLED_CUTOFF = 24_500.0

#: Share of samples at or past full scale, in percent, above which a file is
#: flagged as clipping. Decoded loud masters go past full scale routinely —
#: the reference library's median is 0.0009% and its 90th percentile 0.054% —
#: so a lower line flags a tenth of a club library and means nothing. At 0.1%
#: it is the worst 6% (227 of 3,663), one sample in a thousand.
CLIP_RATE_PCT = 0.1

#: Decode errors needed before a file is flagged. One or two "Header missing"
#: frames are stray bytes the decoder skips: all 33 files on the reference
#: library with any had one or two, and each decoded to its header's length
#: within 0.05 s, i.e. lost no audio. The count is always in the report.
DECODE_ERRORS_FLAG = 3

#: Relative difference between a claimed and the measured bitrate that counts
#: as a disagreement. VBR averages wander by a few percent; a header taken from
#: one frame is off by several times.
BITRATE_TOLERANCE = 0.15

#: Seconds a claimed length may differ from the decoded one. Rekordbox stores
#: whole seconds, so its tolerance is wider.
DURATION_TOLERANCE = 1.0
RB_DURATION_TOLERANCE = 2.0

#: Stereo correlation at or above this is one signal on two channels.
DUAL_MONO_CORRELATION = 0.9999


@dataclass(frozen=True)
class Flag:
    kind: str   # stable, for counting: "transcode?", "clipping", "rekordbox bitrate", ...
    text: str   # the sentence for the report


def flags(m: Measurement, meta: AudioHeader, rb: Optional[RekordboxFile]) -> list[Flag]:
    """Every flag for one file, in the order the report lists them."""
    if m.error:
        return [Flag("undecodable", "undecodable")]
    return list(_audio(m)) + list(_claims(m, meta, rb))


def _audio(m: Measurement) -> Iterator[Flag]:
    """Problems in the audio itself, whatever anything claims."""
    lossless = is_lossless(m.codec)
    cutoff = m.cutoff_hz / 1000 if m.cutoff_hz else None

    if m.cutoff_sharp and m.cutoff_hz:
        if not lossless and m.bitrate_kbps:
            floor = next((hz for kbps, hz in LOSSY_CUTOFF_FLOORS if m.bitrate_kbps >= kbps), None)
            if floor and m.cutoff_hz < floor:
                yield Flag("transcode?", f"transcode? {cutoff:.1f} kHz cutoff at {m.bitrate_kbps:.0f} kbps")
        if lossless and m.cutoff_hz < LOSSLESS_CUTOFF_FLOOR:
            yield Flag("lossy source?", f"lossy source? {cutoff:.1f} kHz cutoff in {m.codec}")
        elif lossless and m.sample_rate and m.sample_rate > 44_100 and m.cutoff_hz < UPSAMPLED_CUTOFF:
            yield Flag("upsampled?",
                       f"upsampled? nothing above {cutoff:.1f} kHz at {m.sample_rate / 1000:g} kHz")

    if m.bit_depth and m.stored_bit_depth and m.bit_depth < m.stored_bit_depth:
        yield Flag("padded bits", f"{m.bit_depth}-bit audio stored as {m.stored_bit_depth}-bit")

    rate = clip_rate_pct(m)
    if rate is not None and rate >= CLIP_RATE_PCT:
        yield Flag("clipping", f"clipping: {rate:.3f}% of samples at full scale")

    if m.decode_errors and m.decode_errors >= DECODE_ERRORS_FLAG:
        yield Flag("decode errors", f"{m.decode_errors} frame(s) failed to decode")

    if m.stereo_correlation is not None:
        if m.stereo_correlation >= DUAL_MONO_CORRELATION:
            yield Flag("mono in stereo", "mono in stereo: both channels carry the same signal")
        elif m.stereo_correlation < 0:
            yield Flag("out of phase",
                       f"out of phase: channel correlation {m.stereo_correlation:.2f}, cancels when summed to mono")


def _claims(m: Measurement, meta: AudioHeader, rb: Optional[RekordboxFile]) -> Iterator[Flag]:
    """Claims the measurement contradicts."""
    lossless = is_lossless(m.codec)

    # Bitrate is a quality claim only for lossy audio; a lossless file's is
    # just its compression ratio.
    if not lossless and m.bitrate_kbps:
        if meta.bitrate_kbps and _differs(meta.bitrate_kbps, m.bitrate_kbps):
            yield Flag("header bitrate",
                       f"header says {meta.bitrate_kbps:.0f} kbps, stream averages {m.bitrate_kbps:.0f}")
        if rb and rb.bitrate_kbps and _differs(rb.bitrate_kbps, m.bitrate_kbps):
            yield Flag("rekordbox bitrate",
                       f"rekordbox says {rb.bitrate_kbps} kbps, stream averages {m.bitrate_kbps:.0f}")

    if m.sample_rate:
        if meta.sample_rate and meta.sample_rate != m.sample_rate:
            yield Flag("header sample rate", f"header says {meta.sample_rate} Hz, decodes at {m.sample_rate}")
        if rb and rb.sample_rate and rb.sample_rate != m.sample_rate:
            yield Flag("rekordbox sample rate",
                       f"rekordbox says {rb.sample_rate} Hz, decodes at {m.sample_rate}")

    if lossless and rb and rb.bit_depth and meta.bit_depth and rb.bit_depth != meta.bit_depth:
        yield Flag("rekordbox bit depth", f"rekordbox says {rb.bit_depth}-bit, header {meta.bit_depth}-bit")

    if m.duration_seconds:
        if meta.duration_seconds and abs(meta.duration_seconds - m.duration_seconds) > DURATION_TOLERANCE:
            yield Flag("header length",
                       f"header says {meta.duration_seconds:.0f}s, decodes to {m.duration_seconds:.0f}s")
        if rb and rb.duration_seconds and abs(rb.duration_seconds - m.duration_seconds) > RB_DURATION_TOLERANCE:
            yield Flag("rekordbox length",
                       f"rekordbox says {rb.duration_seconds}s, decodes to {m.duration_seconds:.0f}s")


def clip_rate_pct(m: Measurement) -> Optional[float]:
    if m.clipped_samples is None or not m.total_samples:
        return None
    return 100.0 * m.clipped_samples / m.total_samples


def _differs(claimed: float, measured: float) -> bool:
    return abs(claimed - measured) > BITRATE_TOLERANCE * measured
