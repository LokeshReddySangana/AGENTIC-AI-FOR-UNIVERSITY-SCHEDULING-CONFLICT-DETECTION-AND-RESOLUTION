"""Candidate domain construction for a session that needs to move."""
from __future__ import annotations

from typing import Dict, List

from ..models import Placement, ScheduleView, Session


def candidate_slots(view, session: Session) -> List[int]:
    out = []
    for sid, slot in view.slots.items():
        if session.kind == "exam" and not slot.is_exam:
            continue
        if session.kind != "exam" and slot.is_exam:
            continue
        out.append(sid)
    # prefer slots on the same day, then nearby times
    current = view.slots[session.slot_id]
    out.sort(key=lambda i: (view.slots[i].day != current.day,
                            abs(view.slots[i].start - current.start),
                            view.slots[i].id))
    return out


def candidate_rooms(view, session: Session) -> List[int]:
    students = view.enrolment(session)
    out = []
    for rid, room in view.rooms.items():
        if room.capacity < students:
            continue
        if session.kind == "exam" and room.kind != "exam_hall":
            continue
        if session.kind == "lab" and room.kind != "lab":
            continue
        if not set(session.required_features) <= set(room.features):
            continue
        out.append(rid)
    # prefer the tightest room that fits (better utilisation)
    out.sort(key=lambda i: (view.rooms[i].capacity, view.rooms[i].id))
    return out


def candidate_faculty(view, session: Session) -> List[int]:
    """Original instructor first, then qualified substitutes for the course."""
    out = [session.faculty_id]
    for fid, fac in view.faculty.items():
        if fid in out:
            continue
        if view.faculty_hours(fid) + view.slots[session.slot_id].duration // 60 > fac.max_hours_week:
            continue
        out.append(fid)
    return out


def build_domain(view, session: Session, limit: int = 400) -> List[Placement]:
    """All (slot, room, faculty) triples worth validating for this session."""
    slots = candidate_slots(view, session)
    rooms = candidate_rooms(view, session)
    faculty = candidate_faculty(view, session)
    current_faculty = [session.faculty_id]
    domain: List[Placement] = []

    # 1. time shift + room change, same instructor (largest useful set)
    for slot_id in slots:
        for room_id in rooms:
            domain.append(Placement(slot_id, room_id, session.faculty_id))
            if len(domain) >= limit:
                return domain
    # 2. faculty substitution in the original slot, then anywhere
    for fid in faculty[1:]:
        domain.append(Placement(session.slot_id, session.room_id, fid))
        for room_id in rooms[:6]:
            domain.append(Placement(session.slot_id, room_id, fid))
    return domain[: limit + 20]
