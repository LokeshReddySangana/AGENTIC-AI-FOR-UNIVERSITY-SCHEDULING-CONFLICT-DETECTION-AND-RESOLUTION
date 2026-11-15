"""Multi-criteria scoring of a proposed repair.

Criteria (all 0..1, higher is better):
  disruption — how much the affected students' week changes
  faculty    — instructor continuity and workload pressure
  room       — room adequacy / utilisation efficiency
  continuity — fraction of session attributes preserved
  margin     — remaining slack on tight constraints
"""
from __future__ import annotations

from typing import Dict, List

from ..models import Context, Placement, ScheduleView

DEFAULT_POLICY = {
    "disruption": 0.30,
    "faculty": 0.20,
    "room": 0.15,
    "continuity": 0.20,
    "margin": 0.15,
}

CRITERIA = ["disruption", "faculty", "room", "continuity", "margin"]


def evaluate_patch(ctx: Context, patch: List[dict]) -> Dict[str, float]:
    overrides = {
        p["session_id"]: Placement(p["slot_id"], p["room_id"], p["faculty_id"]) for p in patch
    }
    view = ScheduleView(ctx, overrides)

    disruption_parts: List[float] = []
    faculty_parts: List[float] = []
    room_parts: List[float] = []
    continuity_parts: List[float] = []
    margin_parts: List[float] = []

    for p in patch:
        sid = p["session_id"]
        old = ctx.sessions[sid]
        new = view.sessions[sid]
        old_slot = ctx.slots[old.slot_id]
        new_slot = ctx.slots[new.slot_id]
        room = ctx.rooms[new.room_id]
        students = view.enrolment(new)

        # --- student disruption: time displacement and day change
        shift = abs(new_slot.start - old_slot.start) / 300.0
        day_change = 0.35 if new_slot.day != old_slot.day else 0.0
        size_weight = min(1.0, students / 120.0)
        disruption_parts.append(
            max(0.0, 1.0 - min(1.0, shift + day_change)) * (0.5 + 0.5 * size_weight)
        )

        # --- faculty impact
        if new.faculty_id == old.faculty_id:
            hours = view.faculty_hours(new.faculty_id)
            cap = ctx.faculty[new.faculty_id].max_hours_week
            pressure = max(0.0, (hours - 0.8 * cap) / max(cap, 1))
            faculty_parts.append(max(0.0, 1.0 - pressure * 2))
        else:
            sub_hours = view.faculty_hours(new.faculty_id)
            sub_cap = ctx.faculty[new.faculty_id].max_hours_week
            headroom = max(0.0, (sub_cap - sub_hours) / max(sub_cap, 1))
            faculty_parts.append(0.45 + 0.35 * min(1.0, headroom * 3))

        # --- room adequacy
        ratio = students / max(room.capacity, 1)
        adequacy = 1.0 - min(1.0, abs(ratio - 0.75) / 0.75)
        feature_surplus = len(room.features - set(new.required_features))
        room_parts.append(max(0.0, adequacy - 0.03 * feature_surplus))

        # --- continuity: preserved attributes
        preserved = (
            (new.room_id == old.room_id) + (new.slot_id == old.slot_id) + (new.faculty_id == old.faculty_id)
        )
        continuity_parts.append(preserved / 3.0)

        # --- rule margin: capacity headroom and availability headroom
        cap_headroom = min(1.0, (room.capacity - students) / max(room.capacity, 1) / 0.30)
        leave_clear = 1.0
        for a in ctx.availability:
            if a["faculty_id"] != new.faculty_id or a["kind"] != "leave":
                continue
            if a["day"] != new_slot.day:
                continue
            if a["start"] < new_slot.end and new_slot.start < a["end"]:
                leave_clear = 0.0
        margin_parts.append(0.7 * cap_headroom + 0.3 * leave_clear)

    def avg(values: List[float]) -> float:
        return round(sum(values) / len(values), 4) if values else 0.0

    return {
        "disruption": avg(disruption_parts),
        "faculty": avg(faculty_parts),
        "room": avg(room_parts),
        "continuity": avg(continuity_parts),
        "margin": avg(margin_parts),
    }


def total_score(breakdown: Dict[str, float], policy: Dict[str, float] | None = None) -> float:
    w = policy or DEFAULT_POLICY
    norm = sum(w.get(k, 0.0) for k in CRITERIA) or 1.0
    return round(sum(w.get(k, 0.0) * breakdown.get(k, 0.0) for k in CRITERIA) / norm, 4)
