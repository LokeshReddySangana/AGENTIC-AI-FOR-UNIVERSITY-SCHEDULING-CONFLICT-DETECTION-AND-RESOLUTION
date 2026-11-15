"""Detection -> resolution -> approval workflow shared by the API and CLI."""
from __future__ import annotations

from typing import Dict, List, Optional

from .. import db
from ..constraints.soft import schedule_penalty
from ..detection.sweep import detect, summarise
from ..models import Placement, ScheduleView
from ..resolution.csp import preview, resolve


def run_detection(actor: str = "scheduler") -> dict:
    ctx = db.load_context()
    conflicts = detect(ctx)
    ids = db.add_conflicts(conflicts)
    for c, cid in zip(conflicts, ids):
        c["conflict_id"] = cid
    db.audit(actor, "detect", {"conflicts": len(conflicts), "summary": summarise(conflicts)})
    return {
        "conflicts": conflicts,
        "summary": summarise(conflicts),
        "version": ctx.version,
        "sessions": len(ctx.sessions),
    }


def resolve_conflict(conflict_id: int, max_alternatives: int = 6) -> dict:
    ctx = db.load_context()
    conflict = db.get_conflict(conflict_id)
    if conflict is None:
        raise KeyError("conflict not found")
    policy = db.get_policy()
    alternatives = resolve(ctx, conflict, policy, max_alternatives=max_alternatives)
    stored = db.replace_alternatives(conflict_id, alternatives, ctx.version)
    # keep explanations and scores from the ranked list
    for a in stored:
        a["score"] = a["score"]
    db.audit("scheduler", "propose", {"conflict_id": conflict_id, "alternatives": len(stored)})
    return {
        "conflict": conflict,
        "alternatives": stored,
        "policy": policy,
        "generated_at_version": ctx.version,
        "solver": "csp+forward-checking",
    }


def preview_alternative(alternative_id: int) -> dict:
    ctx = db.load_context()
    alt = db.get_alternative(alternative_id)
    if alt is None:
        raise KeyError("alternative not found")
    before = schedule_penalty(ScheduleView(ctx), ctx.sessions)
    result = preview(ctx, alt["patch"])
    result["patch_clean"] = _patch_is_clean(ctx, alt["patch"])
    result["baseline_violations"] = preview(ctx, [])["hard_violations"]
    return {"alternative": alt, "before": before, **result}


def _patch_is_clean(ctx, patch: List[dict]) -> bool:
    """True when every session in the patch satisfies all hard constraints."""
    from ..constraints import validate_placement
    from ..models import Placement

    overrides = {
        p["session_id"]: Placement(p["slot_id"], p["room_id"], p["faculty_id"]) for p in patch
    }
    view = ScheduleView(ctx, overrides)
    return all(not validate_placement(view, p["session_id"]) for p in patch)


def apply_alternative(alternative_id: int, actor: str = "scheduler", expected_version: Optional[int] = None) -> dict:
    ctx = db.load_context()
    alt = db.get_alternative(alternative_id)
    if alt is None:
        raise KeyError("alternative not found")
    if expected_version is not None and expected_version != ctx.version:
        raise ValueError(
            f"schedule changed since you loaded it (version {ctx.version} != {expected_version}); re-detect"
        )

    snap = db.snapshot()
    result = preview(ctx, alt["patch"])
    baseline = preview(ctx, [])["hard_violations"]
    if not _patch_is_clean(ctx, alt["patch"]) or result["hard_violations"] > baseline:
        raise ValueError(
            "alternative is no longer feasible: "
            + "; ".join(c["message"] for c in result["new_conflicts"][:3])
        )

    for p in alt["patch"]:
        db.update_session_placement(p["session_id"], p["room_id"], p["slot_id"], p["faculty_id"])
    new_version = db.bump_version()
    db.resolve_conflict(alt["conflict_id"])
    db.audit(
        actor,
        "apply",
        {"alternative_id": alternative_id, "conflict_id": alt["conflict_id"], "patch": alt["patch"],
         "version": new_version, "snapshot": snap},
    )

    ctx2 = db.load_context()
    remaining = detect(ctx2)
    db.add_conflicts(remaining)
    return {
        "applied": alt["patch"],
        "version": new_version,
        "penalty_before": result["penalty"] if "penalty" in result else None,
        "remaining_conflicts": summarise(remaining),
        "rollback_available": True,
    }


def schedule_view() -> dict:
    ctx = db.load_context()
    sessions = []
    for sid, s in sorted(ctx.sessions.items()):
        slot = ctx.slots[s.slot_id]
        room = ctx.rooms[s.room_id]
        course = ctx.courses.get(s.course_id)
        sessions.append(
            {
                "id": sid,
                "course": course.code if course else "?",
                "title": course.title if course else "",
                "kind": s.kind,
                "day": slot.day,
                "start": slot.start,
                "end": slot.end,
                "slot_label": slot.label,
                "room": room.code,
                "faculty": ctx.faculty[s.faculty_id].name,
                "groups": [ctx.group_name(g) for g in s.group_ids],
                "students": ctx.enrolment(s),
                "pinned": s.pinned,
            }
        )
    return {
        "term": ctx.term,
        "version": ctx.version,
        "sessions": sessions,
        "rooms": [{"id": r.id, "code": r.code, "capacity": r.capacity, "kind": r.kind} for r in ctx.rooms.values()],
        "slots": [
            {"id": s.id, "day": s.day, "start": s.start, "end": s.end, "label": s.label, "is_exam": s.is_exam}
            for s in sorted(ctx.slots.values(), key=lambda x: (x.day, x.start))
        ],
        "penalty": schedule_penalty(ScheduleView(ctx), ctx.sessions),
    }


def move_session(session_id: int, slot_id: int, room_id: int, faculty_id: int) -> dict:
    ctx = db.load_context()
    if session_id not in ctx.sessions:
        raise KeyError("session not found")
    patch = [{"session_id": session_id, "slot_id": slot_id, "room_id": room_id, "faculty_id": faculty_id}]
    result = preview(ctx, patch)
    baseline = preview(ctx, [])["hard_violations"]
    if not _patch_is_clean(ctx, patch) or result["hard_violations"] > baseline:
        return {"applied": False, **result}
    snap = db.snapshot()
    db.update_session_placement(session_id, room_id, slot_id, faculty_id)
    version = db.bump_version()
    db.audit("scheduler", "manual-move", {"patch": patch, "version": version, "snapshot": snap})
    return {"applied": True, "version": version, "penalty": result["penalty"]}
