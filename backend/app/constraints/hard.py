"""Hard constraints (H1-H8). Each function returns a Violation or None."""
from __future__ import annotations

from ..models import Placement, Session, Violation
from .registry import pair, single


def overlaps(slot_a, slot_b) -> bool:
    return slot_a.day == slot_b.day and slot_a.start < slot_b.end and slot_b.start < slot_a.end


# --------------------------------------------------------------------- H1-H3
@pair("C1", "H1", "critical")
def room_clash(a_id: int, b_id: int, view):
    a, b = view.sessions[a_id], view.sessions[b_id]
    if a.room_id != b.room_id:
        return None
    if not overlaps(view.slots[a.slot_id], view.slots[b.slot_id]):
        return None
    room = view.rooms[a.room_id]
    return Violation(
        "C1",
        "H1",
        "critical",
        1.0,
        f"{view.describe(a_id)} and {view.describe(b_id)} are both booked in "
        f"{room.code} on {view.slots[a.slot_id].label}.",
    )


@pair("C2", "H2", "critical")
def faculty_clash(a_id: int, b_id: int, view):
    a, b = view.sessions[a_id], view.sessions[b_id]
    if a.faculty_id != b.faculty_id:
        return None
    if not overlaps(view.slots[a.slot_id], view.slots[b.slot_id]):
        return None
    fac = view.faculty[a.faculty_id]
    return Violation(
        "C2",
        "H2",
        "critical",
        1.0,
        f"{fac.name} is scheduled for {view.describe(a_id)} and {view.describe(b_id)} "
        f"at the same time on {view.slots[a.slot_id].label}.",
    )


@pair("C3", "H3", "critical")
def group_clash(a_id: int, b_id: int, view):
    a, b = view.sessions[a_id], view.sessions[b_id]
    shared = set(a.group_ids) & set(b.group_ids)
    if not shared:
        return None
    if not overlaps(view.slots[a.slot_id], view.slots[b.slot_id]):
        return None
    names = ", ".join(view.group_name(g) for g in sorted(shared))
    students = sum(view.groups[g].strength for g in shared if g in view.groups)
    impact = min(1.0, students / 150.0)
    return Violation(
        "C3",
        "H3",
        "critical",
        impact,
        f"{names} are in both {view.describe(a_id)} and {view.describe(b_id)} "
        f"at {view.slots[a.slot_id].label} ({students} students affected).",
    )


# ------------------------------------------------------------------------ H4
@single("C4", "H4", "high")
def room_capacity(session: Session, placement: Placement, view):
    room = view.rooms.get(placement.room_id)
    if room is None:
        return None
    students = view.enrolment(session)
    if students <= room.capacity:
        return None
    overflow = students - room.capacity
    impact = min(1.0, overflow / max(room.capacity, 1))
    return Violation(
        "C4",
        "H4",
        "high",
        impact,
        f"{students} students assigned to {room.code}, which seats {room.capacity} "
        f"({overflow} over capacity).",
    )


# ------------------------------------------------------------------------ H5
@single("C5", "H5", "high")
def room_features(session: Session, placement: Placement, view):
    room = view.rooms.get(placement.room_id)
    if room is None:
        return None
    missing = set(session.required_features) - set(room.features)
    if not missing and session.kind == "lab" and room.kind != "lab":
        missing = {"lab_bench"}
    if not missing:
        return None
    return Violation(
        "C5",
        "H5",
        "high",
        0.8,
        f"{room.code} ({room.kind}) lacks required equipment: {', '.join(sorted(missing))}.",
    )


# ------------------------------------------------------------------------ H6
@single("C6", "H6", "high")
def faculty_availability(session: Session, placement: Placement, view):
    slot = view.slots.get(placement.slot_id)
    fac = view.faculty.get(placement.faculty_id)
    if slot is None or fac is None:
        return None
    if view.faculty_leave(placement.faculty_id, slot.day, slot.start, slot.end):
        return Violation(
            "C6",
            "H6",
            "high",
            1.0,
            f"{fac.name} is on approved leave on {slot.label}.",
        )
    windows = [
        a
        for a in view.availability
        if a["faculty_id"] == placement.faculty_id
        and a["kind"] == "available"
        and a["day"] == slot.day
    ]
    if windows and not any(
        w["start"] <= slot.start and slot.end <= w["end"] for w in windows
    ):
        return Violation(
            "C6",
            "H6",
            "high",
            0.85,
            f"{fac.name} is not available on {slot.label} (declared availability only).",
        )
    return None


# ------------------------------------------------------------------------ H7
@single("C7", "H7", "medium")
def curriculum_rule(session: Session, placement: Placement, view):
    """A group may not sit the same course more than twice on one day."""
    slot = view.slots.get(placement.slot_id)
    if slot is None:
        return None
    for g in session.group_ids:
        same = [
            i
            for i in view.by_group.get(g, [])
            if i != session.id
            and view.sessions[i].course_id == session.course_id
            and view.slots[view.sessions[i].slot_id].day == slot.day
        ]
        if len(same) >= 2:
            course = view.courses.get(session.course_id)
            code = course.code if course else "course"
            return Violation(
                "C7",
                "H7",
                "medium",
                0.6,
                f"{view.group_name(g)} would have {len(same) + 1} {code} sessions on "
                f"{view.slots[slot.id].label.split()[0]} (rule: max 2 per day).",
            )
    return None


@single("C7", "H7", "medium")
def group_day_load(session: Session, placement: Placement, view):
    """Institutional daily load cap per student group."""
    slot = view.slots.get(placement.slot_id)
    if slot is None:
        return None
    for g in session.group_ids:
        n = sum(
            1
            for i in view.by_group.get(g, [])
            if i != session.id and view.slots[view.sessions[i].slot_id].day == slot.day
        )
        if n + 1 > view.day_load_cap:
            return Violation(
                "C7",
                "H7",
                "medium",
                0.7,
                f"{view.group_name(g)} would have {n + 1} sessions on "
                f"{view.slots[slot.id].label.split()[0]} (daily cap {view.day_load_cap}).",
            )
    return None


# ------------------------------------------------------------------------ H8
@single("C8", "H8", "high")
def exam_window(session: Session, placement: Placement, view):
    slot = view.slots.get(placement.slot_id)
    if slot is None:
        return None
    if session.kind == "exam" and not slot.is_exam:
        return Violation(
            "C8", "H8", "high", 0.9, f"Exam placed outside the examination window ({slot.label})."
        )
    if session.kind != "exam" and slot.is_exam:
        return Violation(
            "C8",
            "H8",
            "high",
            0.9,
            f"{view.describe(session.id)} placed inside the examination window ({slot.label}).",
        )
    return None
