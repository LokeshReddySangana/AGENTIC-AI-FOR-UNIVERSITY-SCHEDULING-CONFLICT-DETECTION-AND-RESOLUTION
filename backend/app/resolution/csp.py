"""Resolution engine: propose feasible repairs for a conflict.

Pipeline: candidate domain -> hard-constraint filter (shared registry) ->
strategy classification -> scoring -> ranked shortlist. When no single move
works (a linked conflict group), a bounded joint repair is attempted.
"""
from __future__ import annotations

import time
from typing import Dict, List, Optional

from ..constraints import validate_placement
from ..detection.grouping import linked_groups
from ..models import Context, Placement, ScheduleView
from ..scoring.rank import rank_alternatives
from .domain import build_domain, candidate_rooms, candidate_slots

MAX_SINGLE_CANDIDATES = 400


def _strategy(orig) -> str:
    room_moved = orig["room_id"] is not None
    slot_moved = orig["slot_id"] is not None
    fac_moved = orig["faculty_id"] is not None
    if slot_moved and room_moved and fac_moved:
        return "A4-combined"
    if slot_moved and room_moved:
        return "A1+A2"
    if slot_moved:
        return "A1-time-shift"
    if room_moved:
        return "A2-room-change"
    if fac_moved:
        return "A3-faculty-substitution"
    return "A1-time-shift"


def _feasible(view, session_id: int) -> bool:
    return not validate_placement(view, session_id)


def _single_move_alternatives(
    ctx: Context, session_ids: List[int], budget_s: float, per_strategy: int = 4
) -> List[dict]:
    started = time.monotonic()
    out: List[dict] = []
    counters: Dict[str, int] = {}
    checked = 0

    for sid in session_ids:
        session = ctx.sessions[sid]
        if session.pinned:
            continue
        domain = build_domain(ScheduleView(ctx), session)
        for p in domain:
            if time.monotonic() - started > budget_s:
                return out
            if checked >= MAX_SINGLE_CANDIDATES:
                break
            checked += 1
            if (p.room_id, p.slot_id, p.faculty_id) == (
                session.room_id,
                session.slot_id,
                session.faculty_id,
            ):
                continue
            view = ScheduleView(ctx, {sid: p})
            if not _feasible(view, sid):
                continue
            orig = {
                "room_id": p.room_id if p.room_id != session.room_id else None,
                "slot_id": p.slot_id if p.slot_id != session.slot_id else None,
                "faculty_id": p.faculty_id if p.faculty_id != session.faculty_id else None,
            }
            strategy = _strategy(orig)
            if counters.get(strategy, 0) >= per_strategy:
                continue
            counters[strategy] = counters.get(strategy, 0) + 1
            out.append(
                {
                    "strategy": strategy,
                    "patch": [
                        {
                            "session_id": sid,
                            "slot_id": p.slot_id,
                            "room_id": p.room_id,
                            "faculty_id": p.faculty_id,
                        }
                    ],
                    "feasible": True,
                }
            )
        if len(out) >= 24:
            break
    return out


def _linked_group_alternatives(
    ctx: Context, group: List[int], budget_s: float, attempts: int = 25
) -> List[dict]:
    """Joint repair: place every session of the linked group without violating hard rules."""
    started = time.monotonic()
    ordered = sorted(group, key=lambda sid: ctx.sessions[sid].pinned)
    overrides: Dict[int, Placement] = {}
    patch: List[dict] = []

    for sid in ordered:
        session = ctx.sessions[sid]
        if session.pinned and len(group) > 1:
            # pinned sessions stay put; others must fit around them
            continue
        if time.monotonic() - started > budget_s:
            return []
        domain = build_domain(ScheduleView(ctx, overrides), session)
        placed = False
        for p in domain:
            if p.slot_id == session.slot_id and p.room_id == session.room_id and p.faculty_id == session.faculty_id:
                continue
            overrides[sid] = p
            view = ScheduleView(ctx, overrides)
            if _feasible(view, sid):
                patch.append(
                    {
                        "session_id": sid,
                        "slot_id": p.slot_id,
                        "room_id": p.room_id,
                        "faculty_id": p.faculty_id,
                    }
                )
                placed = True
                break
            del overrides[sid]
        if not placed:
            return []
    if not patch:
        return []
    # final holistic check: nothing else may break
    final = ScheduleView(ctx, overrides)
    for sid in patch:
        if not _feasible(final, sid["session_id"]):
            return []
    return [{"strategy": "A6-linked-reshuffle", "patch": patch, "feasible": True}]


def resolve(
    ctx: Context,
    conflict: dict,
    policy: Optional[Dict[str, float]] = None,
    max_alternatives: int = 6,
    budget_s: float = 4.0,
) -> List[dict]:
    """Return ranked feasible alternatives for one conflict."""
    started = time.monotonic()
    session_ids = conflict["session_ids"]
    alternatives = _single_move_alternatives(ctx, session_ids, budget_s)

    if not alternatives:
        groups = linked_groups([conflict], max_size=6)
        group = groups[0] if groups else session_ids
        alternatives = _linked_group_alternatives(
            ctx, group, max(2.0, budget_s - (time.monotonic() - started))
        )
        if not alternatives:
            alternatives = _linked_group_alternatives(
                ctx, session_ids, max(1.0, budget_s - (time.monotonic() - started))
            )

    if not alternatives:
        return []

    ranked = rank_alternatives(ctx, alternatives, policy)
    return ranked[:max_alternatives]


def preview(ctx: Context, patch: List[dict]) -> dict:
    """Apply a patch to a view and re-validate the whole schedule."""
    overrides = {
        p["session_id"]: Placement(p["slot_id"], p["room_id"], p["faculty_id"]) for p in patch
    }
    view = ScheduleView(ctx, overrides)
    from ..constraints import validate_schedule

    violations = validate_schedule(view)
    from ..constraints.soft import schedule_penalty

    return {
        "patch": patch,
        "hard_violations": len(violations),
        "new_conflicts": [
            {"session_id": sid, "code": v.code, "severity": v.severity, "message": v.message}
            for sid, v in violations
        ],
        "penalty": schedule_penalty(view, ctx.sessions),
    }
