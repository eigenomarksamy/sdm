"""Parse Rekordbox v5 analysis data from USBANLZ/*.EXT files.

The .2EX (extended) files contain metadata like BPM and key computed by Rekordbox.
Structure is binary with tagged sections: PMAI (metadata), PPTH (path), PSGL, etc.

We extract the file path and BPM/key from each .2EX file and build a lookup table
keyed by file path.
"""
from __future__ import annotations

import os
import struct
from typing import Optional


def build_analysis_lookup(usbanlz_path: str) -> dict[str, dict]:
    """Build a lookup table: file_path -> {bpm, key}.

    Scans all P00x/[hash]/ANLZ*.2EX files, extracts the track path and metadata.
    """
    lookup: dict[str, dict] = {}

    if not os.path.isdir(usbanlz_path):
        return lookup

    # Iterate P000, P001, P002, ...
    for p_folder in os.listdir(usbanlz_path):
        p_path = os.path.join(usbanlz_path, p_folder)
        if not os.path.isdir(p_path) or not p_folder.startswith("P"):
            continue

        # Iterate [hash] folders
        for hash_folder in os.listdir(p_path):
            hash_path = os.path.join(p_path, hash_folder)
            if not os.path.isdir(hash_path):
                continue

            # Look for ANLZ*.2EX files
            for filename in os.listdir(hash_path):
                if filename.endswith(".2EX"):
                    ext_path = os.path.join(hash_path, filename)
                    try:
                        data = _parse_2ex_file(ext_path)
                        if data and "path" in data:
                            lookup[data["path"]] = data
                    except Exception:
                        pass

    return lookup


def _parse_2ex_file(path: str) -> Optional[dict]:
    """Parse a .2EX file and extract path, BPM, key."""
    try:
        with open(path, "rb") as f:
            data = f.read()
    except IOError:
        return None

    result = {}

    # Extract path: scan for UTF-16-LE "/" pattern and decode until aligned null
    idx = data.find(b"\x2f\x00", 0, 1000)  # "/" in UTF-16-LE, search in first 1000 bytes
    if idx >= 0:
        try:
            # Find double-null at even offset from "/" (for UTF-16-LE alignment)
            search_from = idx
            null_pos = -1
            while True:
                null_pos = data.find(b"\x00\x00", search_from)
                if null_pos < 0:
                    break
                if (null_pos - idx) % 2 == 0:
                    break
                search_from = null_pos + 1

            if null_pos > idx:
                path_bytes = data[idx:null_pos]
                path_str = path_bytes.decode("utf-16-le")
                if path_str.startswith("/"):
                    result["path"] = path_str
        except Exception:
            pass

    # Scan for PSGL (beatgrid) section for BPM
    for i in range(len(data) - 8):
        if data[i:i+4] == b"PSGL":
            try:
                size = struct.unpack(">I", data[i+4:i+8])[0]
                if 0 < size < 100000 and i + 8 + size <= len(data):
                    payload = data[i+8:i+8+size]
                    bpm = _extract_bpm_from_payload(payload)
                    if bpm:
                        result["bpm"] = bpm
                        break
            except struct.error:
                pass

    # Scan for PKEY section for key
    for i in range(len(data) - 8):
        if data[i:i+4] == b"PKEY":
            try:
                size = struct.unpack(">I", data[i+4:i+8])[0]
                if 0 < size < 100000 and i + 8 + size <= len(data):
                    payload = data[i+8:i+8+size]
                    key = _extract_key_from_payload(payload)
                    if key:
                        result["key"] = key
                        break
            except struct.error:
                pass

    return result if result else None


def _extract_bpm_from_payload(payload: bytes) -> Optional[float]:
    """Extract BPM from a beatgrid/grid payload.

    BPM is typically stored as a 4-byte float in the grid data.
    The exact offset varies, but common patterns exist.
    """
    if len(payload) < 10:
        return None

    # Try common offsets where BPM float appears
    for offset in [0, 4, 8, 12, 16, 20]:
        if offset + 4 <= len(payload):
            try:
                bpm = struct.unpack(">f", payload[offset:offset+4])[0]
                if 40 <= bpm <= 200:  # Reasonable BPM range for music
                    return bpm
            except struct.error:
                pass

    return None


def _extract_key_from_payload(payload: bytes) -> Optional[str]:
    """Extract musical key from payload.

    Key is typically stored as a 1-byte index (0-23 for 12 keys * 2 for major/minor).
    """
    if len(payload) < 1:
        return None

    KEYS = [
        "C", "G", "D", "A", "E", "B",
        "F#", "C#", "G#", "D#", "A#", "F",
        "Am", "Em", "Bm", "F#m", "C#m", "G#m",
        "D#m", "A#m", "Fm", "Cm", "Gm", "Dm",
    ]

    key_idx = payload[0]
    if 0 <= key_idx < len(KEYS):
        return KEYS[key_idx]

    return None
