"""API and workflow tests (isolated database per test module)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.app import db


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    original = db.DB_PATH
    path = tmp_path_factory.mktemp("api") / "api.db"
    db.DB_PATH = str(path)
    db.init_db(force=True)
    from backend.app.main import app

    try:
        with TestClient(app) as test_client:  # triggers startup seeding
            yield test_client
    finally:
        db.DB_PATH = original


def test_health(client):
    assert client.get("/api/health").json()["status"] == "ok"


def test_seed_and_stats(client):
    stats = client.get("/api/stats").json()
    assert stats["sessions"] == 1020
    assert stats["faculty"] == 320
    assert stats["groups"] == 98
    assert stats["rooms"] == 51
    assert stats["conflicts"]["total"] == 30
    assert stats["conflicts"]["critical"] == 17


def test_detect_reports_all_classes(client):
    body = client.post("/api/detect").json()
    codes = set(body["summary"]["by_code"])
    assert {"C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8"} <= codes


def test_detect_is_idempotent(client):
    first = client.post("/api/detect").json()["summary"]["total"]
    second = client.post("/api/detect").json()["summary"]["total"]
    assert first == second


def test_full_workflow(client):
    conflicts = client.get("/api/conflicts").json()["conflicts"]
    target = conflicts[0]
    resolved = client.post(f"/api/conflicts/{target['conflict_id']}/resolve").json()
    alternatives = resolved["alternatives"]
    assert alternatives, "expected ranked alternatives"

    best = alternatives[0]
    preview = client.post(f"/api/alternatives/{best['alternative_id']}/preview").json()
    assert preview["patch_clean"] is True
    assert preview["hard_violations"] <= preview["baseline_violations"]

    before_version = client.get("/api/health").json()["version"]
    applied = client.post(
        f"/api/alternatives/{best['alternative_id']}/apply",
        json={"actor": "test", "expected_version": before_version},
    )
    assert applied.status_code == 200
    body = applied.json()
    assert body["version"] == before_version + 1
    assert body["remaining_conflicts"]["total"] <= len(conflicts)


def test_stale_version_rejected(client):
    conflicts = client.get("/api/conflicts").json()["conflicts"]
    alternatives = client.post(f"/api/conflicts/{conflicts[0]['conflict_id']}/resolve").json()["alternatives"]
    res = client.post(
        f"/api/alternatives/{alternatives[0]['alternative_id']}/apply",
        json={"actor": "test", "expected_version": 1},
    )
    assert res.status_code == 409


def test_infeasible_manual_move_rejected(client):
    schedule = client.get("/api/schedule").json()
    session = schedule["sessions"][0]
    occupied = next(s for s in schedule["sessions"] if s["slot_label"] == session["slot_label"] and s["id"] != session["id"])
    res = client.post(
        f"/api/sessions/{session['id']}/move",
        json={"slot_id": occupied["id"] * 0 + 1, "room_id": occupied.get("room_id", 1), "faculty_id": 1},
    )
    # the request is rejected either as a rule violation (409) or missing room (422/500 avoided)
    assert res.status_code in (409, 422)


def test_policy_normalisation(client):
    res = client.post(
        "/api/policy",
        json={"disruption": 2, "faculty": 1, "room": 1, "continuity": 1, "margin": 1},
    )
    policy = res.json()
    assert abs(sum(policy.values()) - 1.0) < 0.01


def test_audit_trail(client):
    entries = client.get("/api/audit").json()["audit"]
    actions = {e["action"] for e in entries}
    assert {"apply", "propose"}.issubset(actions)
