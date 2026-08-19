"""Union-find, for collapsing pairwise matches into groups.

Duplicate detection produces *pairs* ("a matches b", "b matches c"); reports
want *groups* ("a, b, c are the same track"). This is the primitive that closes
that gap. Feature-specific group construction stays in the feature.
"""
from __future__ import annotations

from typing import Hashable, Iterable, TypeVar

T = TypeVar("T", bound=Hashable)


class UnionFind:
    """Disjoint-set over arbitrary hashable ids, with path halving."""

    def __init__(self, items: Iterable[T]) -> None:
        self._parent: dict[T, T] = {item: item for item in items}

    def find(self, x: T) -> T:
        parent = self._parent
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(self, x: T, y: T) -> None:
        rx, ry = self.find(x), self.find(y)
        if rx != ry:
            self._parent[rx] = ry
