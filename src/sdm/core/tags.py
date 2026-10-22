"""Reading metadata out of audio files.

Several readers, because the callers need different things:

- `read_basic_tags` (eyed3) returns just title/artist and reports failures to
  the caller. The catalog export uses it — it wants an error list it can print.
- `tracks_from_files` (mutagen) returns full `Track` objects including BPM, key
  and duration, across ID3 and Vorbis containers. The Rekordbox feature uses it
  as its last-resort source when no database is readable.
- `read_title_artist` (mutagen) returns two fields for one file, any format.
  `analyze` uses it to put a name on every row.
- `read_title_artist_raw` is the same read without the "Unknown" substitution,
  for the catalog's missing-metadata report, which has to tell absent from
  unreadable.
- `read_audio_header` (mutagen) is not about names at all: it returns what the
  file's header and tags *claim* about its audio — bitrate, sample rate, bit
  depth, length, encoder, ReplayGain — for `quality` to diff against a
  measurement.

All are best-effort by design: a file with unreadable tags never aborts the
run. The first three answer "Unknown"; the raw reader answers None.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from sdm.core.track import Track

#: How several values in one tag field are joined into one string. ID3v2.4 lets
#: a text frame hold more than one value — two artists in one TPE1 — and both
#: mutagen and eyed3 hand them back joined with NUL ("Delano Smith\x00Brian
#: Kage"). Left that way the byte reached every report, and nothing that splits
#: artists could see two of them. "/" is what 304 artist tags on the test clone
#: already use, and what `playlist-diff` splits on.
MULTI_VALUE_SEP = "/"


def _join_values(text: str) -> str:
    """A NUL-joined multi-value string as `MULTI_VALUE_SEP`-joined, empty parts dropped."""
    return MULTI_VALUE_SEP.join(part for part in text.split("\x00") if part)


def read_basic_tags(filepath: str) -> tuple[str, str, Optional[str]]:
    """Return `(title, artist, error)` for one file, via eyed3.

    Missing tags become "Unknown". `error` is a message string if the file
    could not be parsed at all, otherwise None.
    """
    import eyed3

    title = "Unknown"
    artist = "Unknown"

    try:
        audiofile = eyed3.load(filepath)

        if audiofile and audiofile.tag:
            title = _join_values(audiofile.tag.title or "") or "Unknown"
            artist = _join_values(audiofile.tag.artist or "") or "Unknown"

    except Exception as e:
        return title, artist, str(e)

    return title, artist, None


def _first(value):
    """Unwrap a tag value to a scalar.

    Vorbis comments are multi-valued, so mutagen hands back a `list` for FLAC and
    OGG; ID3 hands back a frame object that stringifies to its text. Taking
    `[0]` only for the list case is what keeps a FLAC title from arriving as the
    literal string `"['Somefunkydrum']"`.

    An ID3 frame can be multi-valued too, and its own `str` joins the values
    with NUL; they are joined with `MULTI_VALUE_SEP` here instead. A frame whose
    values are all empty comes back as "", which `_tag` treats as absent.
    """
    if isinstance(value, list):
        return value[0] if value else None
    text = getattr(value, "text", None)
    if isinstance(text, list):
        return MULTI_VALUE_SEP.join(str(part) for part in text if str(part))
    return value


def _tag(tags, *names):
    """First non-empty value among `names`, or None.

    The names are tried across container conventions on purpose — `TIT2` is ID3,
    `title` is Vorbis, `©nam` is MP4 — because *sniffing the container does not
    work*: every one of mutagen's tag objects has `.get`, so a previous version
    of this function that branched on `hasattr(tags, "get")` sent FLAC down the
    ID3 path, where `TBPM`/`TKEY` do not exist and the Vorbis lookups below were
    unreachable. Every FLAC in a library therefore came out with no BPM, no key,
    and a list-shaped title. Looking up all the spellings has no such failure
    mode: the names do not collide across formats, so the first hit is right.

    A name the container cannot hold is skipped, not fatal. Vorbis comments
    only allow ASCII keys, so asking a FLAC for MP4's `©ART` *raises*
    `ValueError` instead of returning None — and the lookup only gets that far
    when the field is absent. Before this was caught, a FLAC with no artist tag
    lost its whole read: "Unknown" for both fields here, no BPM or key in
    `tracks_from_files`, and "unreadable" in the missing-metadata report.
    """
    for name in names:
        try:
            value = _first(tags.get(name))
        except ValueError:
            continue
        if value is not None and str(value) != "":
            return value
    return None


def _text(value) -> Optional[str]:
    """A `_tag` result as `str`, or None. MP4 freeform values arrive as bytes."""
    if value is None:
        return None
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def read_title_artist_raw(filepath: str) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Return `(title, artist, error)` for one file, with None for what is absent.

    `read_title_artist` is this with the gaps filled in as "Unknown" and the
    error dropped. That substitution suits a report that wants a name on every
    row, and defeats one asking *which* files have no name: a track tagged with
    the literal title "Unknown" becomes indistinguishable from one with no title
    tag, and a file that could not be parsed from one that is merely untagged.
    The catalog's missing-metadata report needs both distinctions.

    `error` is a message when the file could not be read at all, else None. A
    readable file with no tag block is not an error — that is (None, None, None).
    """
    from mutagen import File

    try:
        audio = File(filepath)
        if audio is None:
            return None, None, "not a recognized audio file"
        if not getattr(audio, "tags", None):
            return None, None, None

        title = _text(_tag(audio.tags, "TIT2", "title", "\xa9nam"))
        artist = _text(_tag(audio.tags, "TPE1", "artist", "\xa9ART"))
        return title, artist, None
    except Exception as e:
        return None, None, str(e) or type(e).__name__


def read_title_artist(filepath: str) -> tuple[str, str]:
    """Return `(title, artist)` for one file, across ID3, Vorbis and MP4.

    The third reader here, and the narrowest. `read_basic_tags` is eyed3 and
    therefore mp3-only; `tracks_from_files` reads everything but is batch-shaped
    and *drops* files whose duration it cannot determine, which is right for the
    duplicate prefilter and wrong for a caller that needs a name for every row.
    This one reads two fields for one file and always answers.

    It goes through `_tag` (via `read_title_artist_raw`), so it inherits the
    cross-container lookup and cannot repeat the FLAC bug documented there.
    Best-effort like its siblings: unreadable tags yield "Unknown" rather than
    raising.
    """
    title, artist, _ = read_title_artist_raw(filepath)
    return title or "Unknown", artist or "Unknown"


@dataclass(frozen=True)
class AudioHeader:
    """What a file says about its own audio, before anything decodes it.

    Every field is a claim — by the encoder that wrote the header, or the
    tagger that wrote the tags — which is the point: `quality` measures the
    same properties and reports where the two disagree. None means the file
    does not say.
    """
    container: Optional[str] = None         # mutagen's name for it: "MP3", "FLAC", "WAVE", "MP4", ...
    codec: Optional[str] = None             # MP4 only, where the container does not decide it: "mp4a.40.2", "alac"
    bitrate_kbps: Optional[float] = None
    bitrate_mode: Optional[str] = None      # "CBR", "VBR", "ABR"; MP3 only, from its Xing/LAME header
    sample_rate: Optional[int] = None
    bit_depth: Optional[int] = None         # lossless only; a lossy format has none to claim
    channels: Optional[int] = None
    duration_seconds: Optional[float] = None
    encoder: Optional[str] = None           # LAME's own header if present, else the encoder tag
    replaygain_db: Optional[float] = None
    replaygain_source: Optional[str] = None  # "tag", or "lame" for the gain LAME stores in its header
    error: Optional[str] = None             # the file could not be read at all


#: Spellings of the ReplayGain track gain across containers. ID3 keeps it in a
#: TXXX frame whose description is case-sensitive to mutagen, and taggers
#: disagree on the case; Vorbis keys are case-insensitive; MP4 uses freeform
#: iTunes atoms, again in either case.
_REPLAYGAIN_NAMES = (
    "TXXX:REPLAYGAIN_TRACK_GAIN",
    "TXXX:replaygain_track_gain",
    "replaygain_track_gain",
    "----:com.apple.iTunes:replaygain_track_gain",
    "----:com.apple.iTunes:REPLAYGAIN_TRACK_GAIN",
)

#: Containers whose audio is uncompressed or losslessly packed, so a bit depth
#: is a real claim. MP4 is decided by its codec instead (ALAC is, AAC is not).
_LOSSLESS_CONTAINERS = ("FLAC", "WAVE", "AIFF")


def read_audio_header(filepath: str) -> AudioHeader:
    """What `filepath`'s header and tags claim about its audio. Never raises.

    The bitrate is mutagen's reading of the header: for an MP3 with a Xing or
    LAME header that is the true average, but for a VBR file without one it is
    the *first frame's* bitrate — which is how a ~130 kbps VBR file ends up
    labelled 32 kbps, and why `quality` measures the stream instead of trusting
    this.
    """
    from mutagen import File

    try:
        audio = File(filepath)
    except Exception as e:
        return AudioHeader(error=str(e) or type(e).__name__)
    if audio is None:
        return AudioHeader(error="not a recognized audio file")

    info = audio.info
    container = type(audio).__name__
    codec = getattr(info, "codec", None) if container == "MP4" else None
    lossless = container in _LOSSLESS_CONTAINERS or codec == "alac"

    mode = getattr(info, "bitrate_mode", None)
    mode_name = getattr(mode, "name", None)
    bitrate = getattr(info, "bitrate", None)

    gain, gain_source = _replaygain(audio.tags), "tag"
    if gain is None:
        gain, gain_source = getattr(info, "track_gain", None), "lame"

    return AudioHeader(
        container=container,
        codec=codec,
        bitrate_kbps=bitrate / 1000 if bitrate else None,
        bitrate_mode=mode_name if mode_name and mode_name != "UNKNOWN" else None,
        sample_rate=getattr(info, "sample_rate", None) or None,
        bit_depth=(getattr(info, "bits_per_sample", None) or None) if lossless else None,
        channels=getattr(info, "channels", None) or None,
        duration_seconds=getattr(info, "length", None) or None,
        encoder=_encoder(info, audio.tags),
        replaygain_db=gain,
        replaygain_source=gain_source if gain is not None else None,
    )


def _encoder(info, tags) -> Optional[str]:
    """LAME's version and settings from the MP3's own header, else the encoder tag.

    The header is preferred because LAME writes it while encoding, and a tagger
    cannot touch it; the tag (`TSSE` and its kin) is whatever the last program to
    *write* the file put there — "Lavf60.3.100" when ffmpeg re-encoded a rip.
    """
    lame = getattr(info, "encoder_info", "") or ""
    if lame:
        settings = getattr(info, "encoder_settings", "") or ""
        return f"{lame} {settings}".strip()
    if tags:
        return _text(_tag(tags, "TSSE", "encoder", "\xa9too"))
    return None


def _replaygain(tags) -> Optional[float]:
    """The ReplayGain track gain in dB, from text like "-6.54 dB", or None."""
    if not tags:
        return None
    text = _text(_tag(tags, *_REPLAYGAIN_NAMES))
    match = re.search(r"[-+]?\d+(?:\.\d+)?", text or "")
    return float(match.group()) if match else None


def tracks_from_files(files: list[str], *, start_idx: int = 0) -> list[Track]:
    """Build `Track` objects for the given audio files from their embedded tags.

    Files whose duration cannot be determined are skipped, since duration is
    what the duplicate prefilter keys on. Ids are sequential from `start_idx`,
    so callers merging several sources pass the running count.
    """
    try:
        from mutagen import File
    except ImportError:
        raise RuntimeError("mutagen is required for ID3 reading. Install with: pip install mutagen")

    tracks: list[Track] = []
    idx = start_idx
    for filepath in files:
        idx += 1
        title = "Unknown"
        artist = "Unknown"
        bpm = None
        duration = None
        key = None

        try:
            audio = File(filepath)
            if audio is None:
                continue

            # Get duration
            if hasattr(audio, "info") and hasattr(audio.info, "length"):
                duration = audio.info.length

            # Get title, artist, BPM, key from tags. One lookup per field across
            # every container's spelling of it — see `_tag`.
            if hasattr(audio, "tags") and audio.tags:
                tags = audio.tags

                title = _tag(tags, "TIT2", "title", "\xa9nam") or "Unknown"
                artist = _tag(tags, "TPE1", "artist", "\xa9ART") or "Unknown"

                if isinstance(title, bytes):
                    title = title.decode("utf-8", errors="replace")
                if isinstance(artist, bytes):
                    artist = artist.decode("utf-8", errors="replace")

                bpm_tag = _tag(tags, "TBPM", "bpm", "tmpo")
                if bpm_tag is not None:
                    try:
                        bpm = float(str(bpm_tag))
                    except (ValueError, TypeError):
                        pass
                    # A "0" BPM tag is a placeholder, not a measurement. Leaving
                    # it as 0.0 would make `require_bpm` count the track as
                    # analyzed and then compare it against nothing.
                    if bpm is not None and bpm <= 0:
                        bpm = None

                key_tag = _tag(tags, "TKEY", "initialkey", "key")
                if key_tag is not None:
                    key = str(key_tag) or None
        except Exception:
            pass

        if duration is None:
            continue

        tracks.append(
            Track(
                id=str(idx),
                title=str(title),
                artist=str(artist),
                file_path=filepath,
                bpm=bpm,
                key=key,
                duration_seconds=duration,
            )
        )
    return tracks
