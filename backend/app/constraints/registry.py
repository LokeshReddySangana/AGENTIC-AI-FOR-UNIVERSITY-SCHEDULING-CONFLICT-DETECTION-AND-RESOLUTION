"""Constraint registry.

Every hard constraint is a pure function registered here. Both the conflict
detector and the resolution engine run constraints through this single code
path, so detection and feasibility can never drift apart.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List

from ..models import Placement, Session, Violation

SINGLE_CHECKS: List = []
PAIR_CHECKS: List = []


@dataclass(frozen=True)
class Meta:
    code: str  # conflict code, e.g. C4
    constraint: str  # rule id, e.g. H4
    severity: str
    check: Callable


def single(code: str, constraint: str, severity: str):
    """Register a check that validates one session's placement on its own."""

    def deco(fn):
        fn.__constraint_meta__ = Meta(code, constraint, severity, fn)
        SINGLE_CHECKS.append(fn)
        return fn

    return deco


def pair(code: str, constraint: str, severity: str):
    """Register a check for two sessions competing for the same resource."""

    def deco(fn):
        fn.__constraint_meta__ = Meta(code, constraint, severity, fn)
        PAIR_CHECKS.append(fn)
        return fn

    return deco


def check_single(session: Session, placement: Placement, ctx) -> List[Violation]:
    out: List[Violation] = []
    for fn in SINGLE_CHECKS:
        v = fn(session, placement, ctx)
        if v is not None:
            out.append(v)
    return out


def check_pair(a_sid: int, b_sid: int, ctx) -> List[Violation]:
    out: List[Violation] = []
    for fn in PAIR_CHECKS:
        v = fn(a_sid, b_sid, ctx)
        if v is not None:
            out.append(v)
    return out


def all_meta() -> List[Dict[str, str]]:
    seen = {}
    for fn in SINGLE_CHECKS + PAIR_CHECKS:
        m: Meta = fn.__constraint_meta__
        seen[m.constraint] = {"constraint": m.constraint, "code": m.code, "severity": m.severity}
    return sorted(seen.values(), key=lambda d: d["constraint"])
