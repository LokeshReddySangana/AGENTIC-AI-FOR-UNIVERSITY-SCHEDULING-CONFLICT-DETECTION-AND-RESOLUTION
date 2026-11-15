"""Feature extraction for the supervised recommendation model.

Every candidate repair is described by 11 numeric features. The labels used for
training are the scheduler's historical accept/reject decisions, so the model is
a binary classifier (supervised) — there is no clustering, dimensionality
reduction or other unsupervised step anywhere in this package.
"""
from __future__ import annotations

from typing import Dict, List

from ..models import Context, Placement, ScheduleView

FEATURES: List[str] = [
    "time_shift",        # 0..1 normalised displacement of the start time
    "day_change",        # binary
    "room_change",       # binary
    "faculty_change",    # binary
    "capacity_ratio",    # students / room capacity
    "faculty_load",      # instructor weekly load / cap
    "continuity",        # preserved attributes / 3
    "start_hour",        # normalised start time of day
    "sessions_moved",    # moved sessions in the patch / 4
    "students_affected", # affected students / 150
    "feature_surplus",   # equipment surplus / 4
]

FEATURE_LABELS = {
    "time_shift": "time displacement",
    "day_change": "day change",
    "room_change": "room change",
    "faculty_change": "instructor change",
    "capacity_ratio": "room fill ratio",
    "faculty_load": "instructor load",
    "continuity": "continuity",
    "start_hour": "start of day",
    "sessions_moved": "sessions moved",
    "students_affected": "students affected",
    "feature_surplus": "equipment surplus",
}


def extract(ctx: Context, patch: List[Dict]) -> List[float]:
    overrides = {
        p["session_id"]: Placement(p["slot_id"], p["room_id"], p["faculty_id"]) for p in patch
    }
    view = ScheduleView(ctx, overrides)

    rows = []
    for p in patch:
        old = ctx.sessions[p["session_id"]]
        new = view.sessions[p["session_id"]]
        old_slot, new_slot = ctx.slots[old.slot_id], ctx.slots[new.slot_id]
        room = ctx.rooms[new.room_id]
        students = view.enrolment(new)
        fac = ctx.faculty[new.faculty_id]
        preserved = (
            (new.room_id == old.room_id) + (new.slot_id == old.slot_id) + (new.faculty_id == old.faculty_id)
        )
        rows.append(
            [
                min(1.0, abs(new_slot.start - old_slot.start) / 300.0),
                1.0 if new_slot.day != old_slot.day else 0.0,
                1.0 if new.room_id != old.room_id else 0.0,
                1.0 if new.faculty_id != old.faculty_id else 0.0,
                min(2.0, students / max(room.capacity, 1)),
                min(2.0, view.faculty_hours(new.faculty_id) / max(fac.max_hours_week, 1)),
                preserved / 3.0,
                new_slot.start / (19 * 60),
                min(1.0, len(patch) / 4.0),
                min(1.0, students / 150.0),
                min(1.0, len(room.features - set(new.required_features)) / 4.0),
            ]
        )

    n = len(rows) or 1
    return [round(sum(r[i] for r in rows) / n, 4) for i in range(len(FEATURES))]
