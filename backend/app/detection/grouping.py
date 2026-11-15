"""Linked-conflict grouping.

Conflicts that share sessions are connected. A single-session repair is often
impossible inside such a linked group (two sessions mutually block each other),
so the resolution engine escalates to a joint re-placement of the whole group.

This is deterministic union-find connectivity over shared resources — a graph
operation, not a learned segmentation. No unsupervised learning is involved.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Dict, List


class _UnionFind:
    def __init__(self):
        self.parent: Dict[int, int] = {}

    def find(self, x: int) -> int:
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def linked_groups(conflicts: List[dict], max_size: int = 8) -> List[List[int]]:
    """Return groups of session ids connected through shared conflicts."""
    uf = _UnionFind()
    for c in conflicts:
        ids = c["session_ids"]
        for other in ids[1:]:
            uf.union(ids[0], other)
    groups: Dict[int, List[int]] = defaultdict(list)
    for c in conflicts:
        for sid in c["session_ids"]:
            root = uf.find(sid)
            if sid not in groups[root]:
                groups[root].append(sid)
    result = [sorted(v) for v in groups.values()]
    result.sort(key=len, reverse=True)
    return [g[:max_size] for g in result]


def linked_group_for(session_id: int, conflicts: List[dict]) -> List[int]:
    for group in linked_groups(conflicts):
        if session_id in group:
            return group
    return [session_id]
