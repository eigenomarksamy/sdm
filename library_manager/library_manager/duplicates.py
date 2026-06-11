"""Two-stage duplicate detection.

Stage 1 (prefilter): bucket tracks by quantized (BPM, key, duration). Anything
that lands in the same bucket as another track is a candidate pair.

Stage 2 (confirm): for every candidate pair, fingerprint both tracks (cached)
and compare. Pairs with similarity >= threshold are linked into a duplicate
group via union-find.

Output groups record which rule(s) matched ("metadata", "fingerprint", or both).
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from itertools import combinations
from typing import Callable, Iterable, Optional

from library_manager.fingerprint import Fingerprint, similarity
from library_manager.rekordbox_reader import Track


@dataclass
class DuplicateGroup:
    group_id: int
    tracks: list[Track] = field(default_factory=list)
    matched_rules: set[str] = field(default_factory=set)  # {"metadata", "fingerprint"}


@dataclass
class DetectionConfig:
    bpm_tolerance: float = 0.5
    duration_tolerance: float = 2.0
    key_must_match: bool = True
    fingerprint_threshold: float = 0.85
    skip_fingerprint: bool = False


def find_duplicates(
    tracks: Iterable[Track],
    config: DetectionConfig,
    *,
    fingerprint_fn: Optional[Callable[[Track], Optional[Fingerprint]]] = None,
    progress: Optional[Callable[[str], None]] = None,
) -> list[DuplicateGroup]:
    tracks = [t for t in tracks if _is_eligible(t, config)]
    log = progress or (lambda _msg: None)

    candidate_pairs = _prefilter_pairs(tracks, config)
    log(f"prefilter: {len(candidate_pairs)} candidate pair(s) from {len(tracks)} eligible track(s)")

    pair_rules: dict[tuple[str, str], set[str]] = defaultdict(set)
    for a, b in candidate_pairs:
        pair_rules[_pair_key(a, b)].add("metadata")

    if not config.skip_fingerprint and fingerprint_fn is not None:
        confirmed = _confirm_with_fingerprints(
            candidate_pairs, fingerprint_fn, config.fingerprint_threshold, log
        )
        for a, b in confirmed:
            pair_rules[_pair_key(a, b)].add("fingerprint")

        if not pair_rules:
            return []

        # When fingerprinting is on, we trust it: keep only pairs the fingerprint confirmed.
        pair_rules = {k: v for k, v in pair_rules.items() if "fingerprint" in v}

    if not pair_rules:
        return []

    return _build_groups(tracks, pair_rules)


def find_duplicates_by_name(
    tracks: Iterable[Track],
    *,
    progress: Optional[Callable[[str], None]] = None,
) -> list[DuplicateGroup]:
    """Group tracks that share the same (title, artist), ignoring analysis data.

    Title and artist are normalized (lowercased, whitespace collapsed) before
    comparison. Tracks with no title and no artist are skipped.
    """
    log = progress or (lambda _msg: None)

    by_name: dict[tuple[str, str], list[Track]] = defaultdict(list)
    for t in tracks:
        key = (_normalize(t.title), _normalize(t.artist))
        if not key[0] and not key[1]:
            continue
        by_name[key].append(t)

    groups: list[DuplicateGroup] = []
    for key, members in sorted(by_name.items()):
        if len(members) < 2:
            continue
        groups.append(
            DuplicateGroup(
                group_id=len(groups) + 1,
                tracks=sorted(members, key=lambda t: (t.artist, t.title, t.id)),
                matched_rules={"title+artist"},
            )
        )
    log(f"title+artist: {len(groups)} duplicate group(s) from {len(by_name)} unique name(s)")
    return groups


def _normalize(s: Optional[str]) -> str:
    return " ".join((s or "").strip().lower().split())


def _is_eligible(t: Track, config: DetectionConfig) -> bool:
    if t.bpm is None or t.duration_seconds is None:
        return False
    if config.key_must_match and not t.key:
        return False
    return True


def _prefilter_pairs(
    tracks: list[Track], config: DetectionConfig
) -> list[tuple[Track, Track]]:
    # Bucket by quantized BPM and duration (and key if required). Quantization
    # uses the tolerance as the bucket width, so two tracks within tolerance
    # land in the same OR adjacent bucket — we check both.
    bpm_step = max(config.bpm_tolerance, 1e-6)
    dur_step = max(config.duration_tolerance, 1e-6)

    buckets: dict[tuple, list[Track]] = defaultdict(list)
    for t in tracks:
        bpm_bin = int(t.bpm / bpm_step)
        dur_bin = int(t.duration_seconds / dur_step)
        key = (t.key if config.key_must_match else None, bpm_bin, dur_bin)
        buckets[key].append(t)

    pairs: list[tuple[Track, Track]] = []
    seen: set[tuple[str, str]] = set()

    for (key, bpm_bin, dur_bin), bucket_tracks in buckets.items():
        # Compare within bucket and with neighbouring bins (covers tolerance edge cases).
        neighbours: list[Track] = []
        for d_bpm in (-1, 0, 1):
            for d_dur in (-1, 0, 1):
                if d_bpm == 0 and d_dur == 0:
                    continue
                neighbours.extend(buckets.get((key, bpm_bin + d_bpm, dur_bin + d_dur), []))

        for a, b in combinations(bucket_tracks, 2):
            if _within_tolerance(a, b, config):
                pk = _pair_key(a, b)
                if pk not in seen:
                    seen.add(pk)
                    pairs.append((a, b))

        for a in bucket_tracks:
            for b in neighbours:
                if a.id == b.id:
                    continue
                if _within_tolerance(a, b, config):
                    pk = _pair_key(a, b)
                    if pk not in seen:
                        seen.add(pk)
                        pairs.append((a, b))

    return pairs


def _within_tolerance(a: Track, b: Track, config: DetectionConfig) -> bool:
    if config.key_must_match and a.key != b.key:
        return False
    if abs((a.bpm or 0) - (b.bpm or 0)) > config.bpm_tolerance:
        return False
    if abs((a.duration_seconds or 0) - (b.duration_seconds or 0)) > config.duration_tolerance:
        return False
    return True


def _confirm_with_fingerprints(
    pairs: list[tuple[Track, Track]],
    fingerprint_fn: Callable[[Track], Optional[Fingerprint]],
    threshold: float,
    log: Callable[[str], None],
) -> list[tuple[Track, Track]]:
    cache: dict[str, Optional[Fingerprint]] = {}

    def get(t: Track) -> Optional[Fingerprint]:
        if t.id not in cache:
            cache[t.id] = fingerprint_fn(t)
        return cache[t.id]

    confirmed: list[tuple[Track, Track]] = []
    for i, (a, b) in enumerate(pairs, start=1):
        fa = get(a)
        fb = get(b)
        if fa is None or fb is None:
            continue
        score = similarity(fa, fb)
        if score >= threshold:
            confirmed.append((a, b))
        if i % 25 == 0:
            log(f"fingerprint: {i}/{len(pairs)} pair(s) compared")

    log(f"fingerprint: {len(confirmed)} pair(s) confirmed out of {len(pairs)}")
    return confirmed


def _build_groups(
    tracks: list[Track],
    pair_rules: dict[tuple[str, str], set[str]],
) -> list[DuplicateGroup]:
    parent: dict[str, str] = {t.id: t.id for t in tracks}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: str, y: str) -> None:
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[rx] = ry

    rules_by_root: dict[str, set[str]] = defaultdict(set)
    for (id_a, id_b), rules in pair_rules.items():
        union(id_a, id_b)

    # Recompute roots after all unions, then attach rules.
    for (id_a, id_b), rules in pair_rules.items():
        rules_by_root[find(id_a)] |= rules

    members: dict[str, list[Track]] = defaultdict(list)
    tracks_by_id = {t.id: t for t in tracks}
    for tid in {tid for pair in pair_rules for tid in pair}:
        members[find(tid)].append(tracks_by_id[tid])

    groups: list[DuplicateGroup] = []
    for i, (root, group_tracks) in enumerate(sorted(members.items()), start=1):
        if len(group_tracks) < 2:
            continue
        groups.append(
            DuplicateGroup(
                group_id=i,
                tracks=sorted(group_tracks, key=lambda t: (t.artist, t.title, t.id)),
                matched_rules=rules_by_root[root],
            )
        )
    return groups


def _pair_key(a: Track, b: Track) -> tuple[str, str]:
    return (a.id, b.id) if a.id < b.id else (b.id, a.id)
