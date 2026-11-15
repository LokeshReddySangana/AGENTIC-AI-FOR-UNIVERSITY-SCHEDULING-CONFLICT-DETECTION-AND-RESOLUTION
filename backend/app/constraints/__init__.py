"""Constraint package: imports the rule modules for their registration side effects."""
from .registry import (  # noqa: F401
    PAIR_CHECKS,
    SINGLE_CHECKS,
    all_meta,
    check_pair,
    check_single,
)
from . import hard  # noqa: F401,E402
from . import soft  # noqa: F401,E402
from ..models import Placement, Violation


def validate_placement(view, session_id: int) -> list:
    """Full hard-constraint validation of one session inside a schedule view."""
    s = view.sessions[session_id]
    p = Placement(s.slot_id, s.room_id, s.faculty_id)
    violations = check_single(s, p, view)
    for other in view.by_slot.get(p.slot_id, []):
        if other == session_id:
            continue
        violations.extend(check_pair(session_id, other, view))
    return violations


def validate_schedule(view) -> list:
    """Validate every session; returns a list of (session_id, violation)."""
    out = []
    for sid in view.sessions:
        for v in validate_placement(view, sid):
            out.append((sid, v))
    return out
