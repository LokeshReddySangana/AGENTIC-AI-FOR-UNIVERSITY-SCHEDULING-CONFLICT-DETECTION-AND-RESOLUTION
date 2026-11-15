"""Engine tests: detection taxonomy, interval semantics, resolution soundness."""
from __future__ import annotations

import json
import os

import pytest

from backend.app import db
from backend.app.constraints import validate_schedule
from backend.app.constraints.hard import overlaps
from backend.app.detection.sweep import detect, summarise
from backend.app.models import (
    Context,
    Course,
    Faculty,
    Group,
    Room,
    ScheduleView,
    Session,
    Slot,
)
from backend.app.resolution.csp import preview, resolve
from backend.app.scoring.criteria import evaluate_patch, total_score

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SAMPLE = os.path.join(ROOT, "data", "sample_university.json")


@pytest.fixture(scope="module")
def ctx(tmp_path_factory) -> Context:
    original = db.DB_PATH
    db.DB_PATH = str(tmp_path_factory.mktemp("engine") / "engine.db")
    db.init_db(force=True)
    with open(SAMPLE, encoding="utf-8") as fh:
        db.seed_from_payload(json.load(fh))
    try:
        yield db.load_context()
    finally:
        db.DB_PATH = original


def small_context() -> Context:
    slots = {
        1: Slot(1, 1, 9 * 60, 10 * 60),
        2: Slot(2, 1, 10 * 60, 11 * 60),
        3: Slot(3, 2, 9 * 60, 10 * 60),
    }
    rooms = {
        1: Room(1, "R1", 40, "lecture", frozenset()),
        2: Room(2, "R2", 50, "lecture", frozenset()),
    }
    faculty = {1: Faculty(1, "F1", 18), 2: Faculty(2, "F2", 18)}
    groups = {1: Group(1, "G1", 35)}
    courses = {1: Course(1, "C1", "Course One", 4)}
    sessions = {
        1: Session(1, 1, 1, 1, 1, "lecture", [1]),
        2: Session(2, 1, 1, 2, 2, "lecture", [1]),
    }
    return Context(slots, rooms, faculty, groups, courses, sessions, [], {"name": "t"})


# ------------------------------------------------------------------ semantics
def test_half_open_intervals_never_clash():
    a, b = Slot(1, 1, 600, 660), Slot(2, 1, 660, 720)
    assert not overlaps(a, b)
    assert not overlaps(b, a)


def test_adjacent_sessions_are_clean():
    ctx = small_context()
    assert detect(ctx) == []


# ------------------------------------------------------------------- taxonomy
def test_room_double_booking_detected():
    ctx = small_context()
    ctx.sessions[2].room_id = 1
    ctx.sessions[2].slot_id = 1
    ctx.rebuild_indexes()
    conflicts = detect(ctx)
    assert any(c["code"] == "C1" and c["severity"] == "critical" for c in conflicts)


def test_faculty_clash_detected():
    ctx = small_context()
    ctx.sessions[2].slot_id = 1
    ctx.sessions[2].room_id = 2
    ctx.rebuild_indexes()
    assert any(c["code"] == "C2" for c in detect(ctx))


def test_group_clash_detected():
    ctx = small_context()
    ctx.sessions[2].slot_id = 1
    ctx.sessions[2].room_id = 2
    ctx.sessions[2].faculty_id = 2
    ctx.rebuild_indexes()
    assert any(c["code"] == "C3" for c in detect(ctx))


def test_capacity_overflow(ctx):
    conflicts = detect(ctx)
    assert any(c["code"] == "C4" for c in conflicts)


def test_equipment_mismatch(ctx):
    assert any(c["code"] == "C5" for c in detect(ctx))


def test_availability_violation(ctx):
    assert any(c["code"] == "C6" for c in detect(ctx))


def test_exam_window_violation(ctx):
    assert any(c["code"] == "C8" for c in detect(ctx))


def test_full_taxonomy_present(ctx):
    codes = {c["code"] for c in detect(ctx)}
    for expected in ["C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8"]:
        assert expected in codes, f"missing {expected}"


def test_summary_counts_match(ctx):
    conflicts = detect(ctx)
    s = summarise(conflicts)
    assert s["total"] == len(conflicts)
    assert s["critical"] >= 3


# ------------------------------------------------------------------ resolution
def test_resolution_returns_feasible_alternatives(ctx):
    conflicts = detect(ctx)
    target = next(c for c in conflicts if c["code"] == "C1")
    alternatives = resolve(ctx, target)
    assert alternatives, "expected at least one repair"
    top = alternatives[0]
    assert top["feasible"] is True
    for criteria in ["disruption", "faculty", "room", "continuity", "margin"]:
        assert 0.0 <= top["score"]["breakdown"][criteria] <= 1.0
    assert "score" in top and top["explanation"]


def test_resolution_soundness(ctx):
    """An alternative must not add violations and must clear the target conflict."""
    from backend.app.constraints import validate_placement

    baseline = preview(ctx, [])["hard_violations"]
    conflicts = [c for c in detect(ctx) if c["code"] in {"C1", "C2", "C3"}][:3]
    for conflict in conflicts:
        for alt in resolve(ctx, conflict, max_alternatives=3):
            result = preview(ctx, alt["patch"])
            assert result["hard_violations"] <= baseline, result["new_conflicts"]
            from backend.app.models import ScheduleView

            view = ScheduleView(
                ctx,
                {
                    p["session_id"]: __import__("backend.app.models", fromlist=["Placement"]).Placement(
                        p["slot_id"], p["room_id"], p["faculty_id"]
                    )
                    for p in alt["patch"]
                },
            )
            for p in alt["patch"]:
                assert validate_placement(view, p["session_id"]) == []


def test_ranking_is_sorted(ctx):
    conflict = next(c for c in detect(ctx) if c["code"] == "C2")
    alternatives = resolve(ctx, conflict, max_alternatives=4)
    totals = [a["score"]["total"] for a in alternatives]
    assert totals == sorted(totals, reverse=True)


# -------------------------------------------------------------------- scoring
def test_scoring_rewards_continuity(ctx):
    session = ctx.sessions[1]
    keep = [{"session_id": 1, "slot_id": session.slot_id, "room_id": session.room_id,
             "faculty_id": session.faculty_id}]
    moved_slot = next(s for s in ctx.slots if s != session.slot_id and not ctx.slots[s].is_exam)
    move = [{"session_id": 1, "slot_id": moved_slot, "room_id": session.room_id,
             "faculty_id": session.faculty_id}]
    keep_score = evaluate_patch(ctx, keep)["continuity"]
    move_score = evaluate_patch(ctx, move)["continuity"]
    assert keep_score > move_score


def test_total_score_bounds():
    breakdown = {"disruption": 1, "faculty": 1, "room": 1, "continuity": 1, "margin": 1}
    assert total_score(breakdown) == pytest.approx(1.0)
    zeros = {k: 0 for k in breakdown}
    assert total_score(zeros) == 0.0
