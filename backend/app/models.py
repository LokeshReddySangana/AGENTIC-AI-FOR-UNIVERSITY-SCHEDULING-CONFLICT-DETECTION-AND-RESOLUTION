"""Domain model for the scheduling agent.

Everything the constraint engine needs is held in memory in a `Context`.
Times are stored as integer minutes from midnight, and sessions occupy the
half-open interval [start, end) so that back-to-back sessions never clash.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, FrozenSet, List, Optional, Tuple


def to_minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def to_hhmm(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


@dataclass(frozen=True)
class Slot:
    id: int
    day: int  # 1 = Monday ... 7 = Sunday
    start: int
    end: int
    is_exam: bool = False

    @property
    def duration(self) -> int:
        return self.end - self.start

    @property
    def label(self) -> str:
        return f"{DAY_NAMES.get(self.day, '?')} {to_hhmm(self.start)}-{to_hhmm(self.end)}"


DAY_NAMES = {1: "Mon", 2: "Tue", 3: "Wed", 4: "Thu", 5: "Fri", 6: "Sat", 7: "Sun"}


@dataclass(frozen=True)
class Room:
    id: int
    code: str
    capacity: int
    kind: str  # lecture | lab | seminar | exam_hall
    features: FrozenSet[str] = frozenset()


@dataclass(frozen=True)
class Faculty:
    id: int
    name: str
    max_hours_week: int = 18


@dataclass(frozen=True)
class Group:
    id: int
    name: str
    strength: int
    programme: str = ""
    semester: int = 1


@dataclass(frozen=True)
class Course:
    id: int
    code: str
    title: str
    credits: int
    required_features: FrozenSet[str] = frozenset()


@dataclass
class Session:
    id: int
    course_id: int
    faculty_id: int
    room_id: int
    slot_id: int
    kind: str = "lecture"  # lecture | tutorial | lab | exam | event
    group_ids: List[int] = field(default_factory=list)
    required_features: FrozenSet[str] = frozenset()
    pinned: bool = False
    status: str = "scheduled"

    def clone(self) -> "Session":
        return Session(
            id=self.id,
            course_id=self.course_id,
            faculty_id=self.faculty_id,
            room_id=self.room_id,
            slot_id=self.slot_id,
            kind=self.kind,
            group_ids=list(self.group_ids),
            required_features=self.required_features,
            pinned=self.pinned,
            status=self.status,
        )


@dataclass(frozen=True)
class Placement:
    """A proposed (slot, room, faculty) triple for one session."""

    slot_id: int
    room_id: int
    faculty_id: int


@dataclass
class Violation:
    code: str
    constraint: str
    severity: str
    impact: float
    message: str

    @property
    def score(self) -> float:
        """0-100 severity score."""
        base = {"critical": 100.0, "high": 75.0, "medium": 50.0, "low": 25.0}.get(
            self.severity, 50.0
        )
        return round(min(100.0, base * (0.75 + 0.25 * min(self.impact, 1.0))), 2)


class Context:
    """In-memory schedule state used by every engine component."""

    def __init__(
        self,
        slots: Dict[int, Slot],
        rooms: Dict[int, Room],
        faculty: Dict[int, Faculty],
        groups: Dict[int, Group],
        courses: Dict[int, Course],
        sessions: Dict[int, Session],
        availability: List[dict],
        term: dict,
        day_load_cap: int = 5,
        version: int = 1,
    ):
        self.slots = slots
        self.rooms = rooms
        self.faculty = faculty
        self.groups = groups
        self.courses = courses
        self.sessions = sessions
        self.availability = availability
        self.term = term
        self.day_load_cap = day_load_cap
        self.version = version
        self.rebuild_indexes()

    # ---------------------------------------------------------------- indexes
    def rebuild_indexes(self) -> None:
        self.by_room: Dict[int, List[int]] = {}
        self.by_faculty: Dict[int, List[int]] = {}
        self.by_group: Dict[int, List[int]] = {}
        self.by_course: Dict[int, List[int]] = {}
        self.by_slot: Dict[int, List[int]] = {}
        for sid, s in self.sessions.items():
            if s.status != "scheduled":
                continue
            self.by_room.setdefault(s.room_id, []).append(sid)
            self.by_faculty.setdefault(s.faculty_id, []).append(sid)
            for g in s.group_ids:
                self.by_group.setdefault(g, []).append(sid)
            self.by_course.setdefault(s.course_id, []).append(sid)
            self.by_slot.setdefault(s.slot_id, []).append(sid)

    # --------------------------------------------------------------- helpers
    def slot_of(self, s: Session) -> Slot:
        return self.slots[s.slot_id]

    def enrolment(self, s: Session) -> int:
        return sum(self.groups[g].strength for g in s.group_ids if g in self.groups)

    def faculty_hours(self, faculty_id: int) -> int:
        """Weekly contact hours currently assigned."""
        minutes = sum(
            self.slots[self.sessions[i].slot_id].duration
            for i in self.by_faculty.get(faculty_id, [])
        )
        return minutes // 60

    def faculty_leave(self, faculty_id: int, day: int, start: int, end: int) -> bool:
        for a in self.availability:
            if a["faculty_id"] != faculty_id or a["kind"] != "leave":
                continue
            if a["day"] != day:
                continue
            if a["start"] < end and start < a["end"]:
                return True
        return False

    def group_name(self, gid: int) -> str:
        g = self.groups.get(gid)
        return g.name if g else f"group {gid}"

    def describe(self, sid: int) -> str:
        s = self.sessions[sid]
        course = self.courses.get(s.course_id)
        label = f"{course.code} {s.kind}" if course else f"session {sid}"
        return label


class ScheduleView:
    """A read-only view of a schedule where one or more sessions are replaced.

    Used by the resolution engine so that candidate placements are validated
    against exactly the same code path as the live schedule.
    """

    def __init__(self, ctx: Context, overrides: Optional[Dict[int, Placement]] = None):
        self.ctx = ctx
        self.overrides: Dict[int, Placement] = overrides or {}
        self.slots = ctx.slots
        self.rooms = ctx.rooms
        self.faculty = ctx.faculty
        self.groups = ctx.groups
        self.courses = ctx.courses
        self.availability = ctx.availability
        self.day_load_cap = ctx.day_load_cap
        self.version = ctx.version
        self.sessions: Dict[int, Session] = {}
        for sid, s in ctx.sessions.items():
            p = self.overrides.get(sid)
            if p is None:
                self.sessions[sid] = s
                continue
            clone = s.clone()
            clone.slot_id = p.slot_id
            clone.room_id = p.room_id
            clone.faculty_id = p.faculty_id
            self.sessions[sid] = clone
        self._build_indexes()

    def session(self, sid: int) -> Session:
        return self.sessions[sid]

    def _build_indexes(self) -> None:
        self.by_room: Dict[int, List[int]] = {}
        self.by_faculty: Dict[int, List[int]] = {}
        self.by_group: Dict[int, List[int]] = {}
        self.by_slot: Dict[int, List[int]] = {}
        for sid, s in self.sessions.items():
            if s.status != "scheduled":
                continue
            self.by_room.setdefault(s.room_id, []).append(sid)
            self.by_faculty.setdefault(s.faculty_id, []).append(sid)
            for g in s.group_ids:
                self.by_group.setdefault(g, []).append(sid)
            self.by_slot.setdefault(s.slot_id, []).append(sid)

    # period helpers, so the view is interchangeable with Context
    def enrolment(self, s: Session) -> int:
        return sum(self.groups[g].strength for g in s.group_ids if g in self.groups)

    def faculty_leave(self, faculty_id: int, day: int, start: int, end: int) -> bool:
        return self.ctx.faculty_leave(faculty_id, day, start, end)

    def faculty_hours(self, faculty_id: int) -> int:
        minutes = sum(
            self.slots[self.sessions[i].slot_id].duration
            for i in self.by_faculty.get(faculty_id, [])
        )
        return minutes // 60

    def group_name(self, gid: int) -> str:
        g = self.groups.get(gid)
        return g.name if g else f"group {gid}"

    def describe(self, sid: int) -> str:
        s = self.sessions[sid]
        course = self.courses.get(s.course_id)
        return f"{course.code} {s.kind}" if course else f"session {sid}"
