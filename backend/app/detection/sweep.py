"""Conflict detection.

Pairwise conflicts are found with a sweep line over each resource axis
(room / faculty / student group), grouped per day, so detection is
O(n log n + k) instead of O(n^2). Single-session rules (capacity, equipment,
availability, curriculum, exam window) are evaluated per session.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Dict, List

from ..constraints import SINGLE_CHECKS
from ..constraints.hard import overlaps
from ..models import Context, Placement

PAIR_CODES = {"room": ("C1", "H1", "critical"), "faculty": ("C2", "H2", "critical"),
              "group": ("C3", "H3", "critical")}


def _as_conflict(v, session_ids: List[int], entities: Dict | None = None) -> dict:
    return {
        "code": v.code,
        "constraint": v.constraint,
        "severity": v.severity,
        "score": v.score,
        "session_ids": sorted(int(i) for i in session_ids),
        "entities": entities or {},
        "message": v.message,
    }


def _pair_conflicts(ctx: Context) -> List[dict]:
    found: Dict[tuple, dict] = {}

    axes = {
        "room": ctx.by_room,
        "faculty": ctx.by_faculty,
        "group": ctx.by_group,
    }
    for axis, index in axes.items():
        for resource_id, session_ids in index.items():
            # group by day so the sweep never compares across days
            per_day: Dict[int, list] = defaultdict(list)
            for sid in session_ids:
                s = ctx.sessions[sid]
                if s.status != "scheduled":
                    continue
                slot = ctx.slots[s.slot_id]
                per_day[slot.day].append((slot.start, slot.end, sid))

            for day, items in per_day.items():
                items.sort(key=lambda t: (t[0], t[1]))
                active: list = []
                for start, end, sid in items:
                    active = [a for a in active if a[1] > start]
                    for a_start, a_end, other in active:
                        if other == sid:
                            continue
                        a, b = ctx.sessions[sid], ctx.sessions[other]
                        key_code = PAIR_CODES[axis][0]
                        key = (key_code, tuple(sorted((sid, other))))
                        if key in found:
                            continue
                        # axis-specific overlap requirement
                        if axis == "room":
                            if a.room_id != b.room_id:
                                continue
                            slot_a, slot_b = ctx.slots[a.slot_id], ctx.slots[b.slot_id]
                            if not overlaps(slot_a, slot_b):
                                continue
                            from ..models import Violation

                            room = ctx.rooms[a.room_id]
                            v = Violation(
                                "C1", "H1", "critical", 1.0,
                                f"{ctx.describe(sid)} and {ctx.describe(other)} are both booked in "
                                f"{room.code} on {slot_a.label}.",
                            )
                            entities = {"room": room.code, "day": slot_a.day,
                                        "start": slot_a.start, "end": slot_a.end}
                        elif axis == "faculty":
                            if a.faculty_id != b.faculty_id:
                                continue
                            slot_a, slot_b = ctx.slots[a.slot_id], ctx.slots[b.slot_id]
                            if not overlaps(slot_a, slot_b):
                                continue
                            from ..models import Violation

                            fac = ctx.faculty[a.faculty_id]
                            v = Violation(
                                "C2", "H2", "critical", 1.0,
                                f"{fac.name} is double-booked: {ctx.describe(sid)} and "
                                f"{ctx.describe(other)} both at {slot_a.label}.",
                            )
                            entities = {"faculty": fac.name, "day": slot_a.day,
                                        "start": slot_a.start, "end": slot_a.end}
                        else:
                            shared = set(a.group_ids) & set(b.group_ids)
                            if not shared:
                                continue
                            slot_a, slot_b = ctx.slots[a.slot_id], ctx.slots[b.slot_id]
                            if not overlaps(slot_a, slot_b):
                                continue
                            from ..models import Violation

                            students = sum(ctx.groups[g].strength for g in shared if g in ctx.groups)
                            names = ", ".join(ctx.group_name(g) for g in sorted(shared))
                            v = Violation(
                                "C3", "H3", "critical", min(1.0, students / 150.0),
                                f"{names} are enrolled in both {ctx.describe(sid)} and "
                                f"{ctx.describe(other)} at {slot_a.label} ({students} students).",
                            )
                            entities = {"groups": [ctx.group_name(g) for g in sorted(shared)],
                                        "students": students, "day": slot_a.day,
                                        "start": slot_a.start, "end": slot_a.end}
                        found[key] = _as_conflict(v, [sid, other], entities)
                    active.append((start, end, sid))
    return list(found.values())


def _single_conflicts(ctx: Context) -> List[dict]:
    """Capacity, equipment, availability, curriculum and exam-window rules."""
    out = []
    seen = set()
    for sid, s in ctx.sessions.items():
        if s.status != "scheduled":
            continue
        p = Placement(s.slot_id, s.room_id, s.faculty_id)
        for fn in SINGLE_CHECKS:
            if fn.__name__ == "group_day_load":
                continue  # covered by the aggregated day-load pass
            v = fn(s, p, ctx)
            if v is None:
                continue
            key = (v.code, v.message)
            if key in seen:
                continue
            seen.add(key)
            slot = ctx.slots[s.slot_id]
            entities = {"day": slot.day, "start": slot.start, "end": slot.end}
            if v.code == "C4":
                entities["room"] = ctx.rooms[s.room_id].code
            if v.code == "C6":
                entities["faculty"] = ctx.faculty[s.faculty_id].name
            out.append(_as_conflict(v, [sid], entities))
    return out


def _day_load_conflicts(ctx: Context) -> List[dict]:
    """One aggregated conflict per (group, day) above the institutional cap."""
    from ..models import Violation

    out = []
    for gid, ids in ctx.by_group.items():
        per_day: Dict[int, list] = defaultdict(list)
        for sid in ids:
            s = ctx.sessions[sid]
            per_day[ctx.slots[s.slot_id].day].append(sid)
        for day, day_ids in per_day.items():
            if len(day_ids) > ctx.day_load_cap:
                v = Violation(
                    "C7", "H7", "medium", 0.7,
                    f"{ctx.group_name(gid)} has {len(day_ids)} sessions on "
                    f"{['', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'][day]} "
                    f"(daily cap {ctx.day_load_cap}).",
                )
                out.append(_as_conflict(v, day_ids, {"group": ctx.group_name(gid), "day": day}))
    return out


def detect(ctx: Context) -> List[dict]:
    """Full conflict scan, highest severity first."""
    conflicts = _pair_conflicts(ctx) + _single_conflicts(ctx) + _day_load_conflicts(ctx)
    conflicts.sort(key=lambda c: (-c["score"], c["code"], c["session_ids"]))
    return conflicts


def detect_incremental(ctx: Context, session_ids: List[int]) -> List[dict]:
    """Conflicts affected by a set of changed sessions."""
    touched = set(session_ids)
    # include sessions sharing a resource with the changed ones
    for sid in list(session_ids):
        s = ctx.sessions.get(sid)
        if s is None:
            continue
        touched.update(ctx.by_room.get(s.room_id, []))
        touched.update(ctx.by_faculty.get(s.faculty_id, []))
        for g in s.group_ids:
            touched.update(ctx.by_group.get(g, []))
    return [c for c in detect(ctx) if set(c["session_ids"]) & touched]


def summarise(conflicts: List[dict]) -> dict:
    by_code: Dict[str, int] = defaultdict(int)
    by_sev: Dict[str, int] = defaultdict(int)
    for c in conflicts:
        by_code[c["code"]] += 1
        by_sev[c["severity"]] += 1
    return {
        "total": len(conflicts),
        "by_code": dict(sorted(by_code.items())),
        "by_severity": dict(by_sev),
        "critical": by_sev.get("critical", 0),
    }
