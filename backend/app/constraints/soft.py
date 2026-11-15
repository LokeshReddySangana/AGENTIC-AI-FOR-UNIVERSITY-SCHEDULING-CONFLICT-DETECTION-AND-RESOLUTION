"""Soft constraints (S1-S6) — penalised preferences, never blocking.

Every function returns a normalised penalty in [0, 1] for the whole schedule
view it is given (0 = perfect).
"""
from __future__ import annotations

from typing import Dict

SOFT_WEIGHTS: Dict[str, float] = {
    "S1_student_gaps": 0.20,
    "S2_faculty_balance": 0.20,
    "S3_room_utilisation": 0.15,
    "S4_time_preference": 0.15,
    "S5_continuity": 0.20,
    "S6_spread": 0.10,
}

DAY_START, DAY_END = 8 * 60, 19 * 60


def _active(view):
    return [view.sessions[i] for i in sorted(view.sessions) if view.sessions[i].status == "scheduled"]


def student_gaps(view) -> float:
    """Idle time between a group's first and last session each day."""
    minutes = 0
    seated = 0
    for gid, ids in view.by_group.items():
        per_day: Dict[int, list] = {}
        for sid in ids:
            s = view.sessions[sid]
            slot = view.slots[s.slot_id]
            per_day.setdefault(slot.day, []).append(slot)
        for slots in per_day.values():
            slots.sort(key=lambda x: x.start)
            seated += sum(sl.duration for sl in slots)
            minutes += slots[-1].end - slots[0].start - sum(sl.duration for sl in slots)
    if not seated:
        return 0.0
    return min(1.0, minutes / (seated * 0.5 + 1))


def faculty_balance(view) -> float:
    if not view.faculty:
        return 0.0
    total = 0.0
    for fid, fac in view.faculty.items():
        target = fac.max_hours_week * 0.75
        hours = view.faculty_hours(fid)
        if target <= 0:
            continue
        total += min(1.0, abs(hours - target) / target)
    return total / len(view.faculty)


def room_utilisation(view) -> float:
    if not view.rooms:
        return 0.0
    total, n = 0.0, 0
    for sid, ids in view.by_room.items():
        room = view.rooms[sid]
        for i in ids:
            s = view.sessions[i]
            ratio = view.enrolment(s) / max(room.capacity, 1)
            total += min(1.0, abs(ratio - 0.75) / 0.75)
            n += 1
    return total / n if n else 0.0


def time_preference(view) -> float:
    sessions = _active(view)
    if not sessions:
        return 0.0
    total = 0.0
    for s in sessions:
        slot = view.slots[s.slot_id]
        penalty = 0.0
        if slot.start < 9 * 60:
            penalty = 0.6
        if slot.end > 18 * 60:
            penalty = max(penalty, 0.8)
        total += penalty
    return total / len(sessions)


def continuity(view, original: Dict[int, "object"]) -> float:
    """Fraction of sessions that moved away from their original placement."""
    sessions = _active(view)
    if not sessions:
        return 0.0
    moved = 0
    for s in sessions:
        o = original.get(s.id)
        if o is None:
            continue
        if (o.room_id, o.slot_id, o.faculty_id) != (s.room_id, s.slot_id, s.faculty_id):
            moved += 1
    return moved / len(sessions)


def spread(view) -> float:
    """Same course appearing twice on the same day for a group."""
    collisions, total = 0, 0
    for gid, ids in view.by_group.items():
        per_day: Dict[tuple, int] = {}
        for sid in ids:
            s = view.sessions[sid]
            key = (view.slots[s.slot_id].day, s.course_id)
            per_day[key] = per_day.get(key, 0) + 1
        for count in per_day.values():
            total += 1
            if count > 1:
                collisions += count - 1
    return min(1.0, collisions / total) if total else 0.0


def schedule_penalty(view, original=None, weights: Dict[str, float] | None = None) -> dict:
    w = weights or SOFT_WEIGHTS
    parts = {
        "S1_student_gaps": student_gaps(view),
        "S2_faculty_balance": faculty_balance(view),
        "S3_room_utilisation": room_utilisation(view),
        "S4_time_preference": time_preference(view),
        "S6_spread": spread(view),
    }
    if original is not None:
        parts["S5_continuity"] = continuity(view, original)
    total = sum(w.get(k, 0.0) * v for k, v in parts.items())
    norm = sum(w.get(k, 0.0) for k in parts) or 1.0
    return {
        "total": round(total / norm, 4),
        "components": {k: round(v, 4) for k, v in parts.items()},
    }
