"""SQLite persistence layer.

The engine works on an in-memory `Context`; this module loads it from disk and
stores conflicts, alternatives and audit records back.
"""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .models import (
    Context,
    Course,
    Faculty,
    Group,
    Room,
    Session,
    Slot,
    to_minutes,
)

DB_PATH = os.environ.get(
    "SCHED_DB",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "schedule.db"),
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS term (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE,
  starts_on TEXT NOT NULL,
  ends_on TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS time_slot (
  id INTEGER PRIMARY KEY,
  day INTEGER NOT NULL,
  start_min INTEGER NOT NULL,
  end_min INTEGER NOT NULL,
  is_exam INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS room (
  id INTEGER PRIMARY KEY,
  code TEXT UNIQUE NOT NULL,
  capacity INTEGER NOT NULL,
  kind TEXT NOT NULL,
  features TEXT DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS faculty (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  email TEXT,
  max_hours_week INTEGER DEFAULT 18
);
CREATE TABLE IF NOT EXISTS student_group (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  strength INTEGER NOT NULL,
  programme TEXT,
  semester INTEGER
);
CREATE TABLE IF NOT EXISTS course (
  id INTEGER PRIMARY KEY,
  code TEXT UNIQUE NOT NULL,
  title TEXT NOT NULL,
  credits INTEGER NOT NULL,
  required_features TEXT DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS session (
  id INTEGER PRIMARY KEY,
  course_id INTEGER REFERENCES course(id),
  faculty_id INTEGER REFERENCES faculty(id),
  room_id INTEGER REFERENCES room(id),
  slot_id INTEGER REFERENCES time_slot(id),
  kind TEXT NOT NULL,
  required_features TEXT DEFAULT '[]',
  pinned INTEGER DEFAULT 0,
  status TEXT DEFAULT 'scheduled'
);
CREATE TABLE IF NOT EXISTS session_group (
  session_id INTEGER REFERENCES session(id) ON DELETE CASCADE,
  group_id INTEGER REFERENCES student_group(id),
  PRIMARY KEY (session_id, group_id)
);
CREATE TABLE IF NOT EXISTS faculty_availability (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  faculty_id INTEGER REFERENCES faculty(id),
  day INTEGER,
  start_min INTEGER,
  end_min INTEGER,
  kind TEXT DEFAULT 'available'
);
CREATE TABLE IF NOT EXISTS conflict (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  detected_at TEXT DEFAULT CURRENT_TIMESTAMP,
  code TEXT NOT NULL,
  constraint_id TEXT DEFAULT '',
  severity TEXT NOT NULL,
  score REAL,
  session_ids TEXT NOT NULL,
  entity_refs TEXT,
  message TEXT NOT NULL,
  status TEXT DEFAULT 'open'
);
CREATE TABLE IF NOT EXISTS alternative (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  conflict_id INTEGER REFERENCES conflict(id) ON DELETE CASCADE,
  strategy TEXT NOT NULL,
  patch TEXT NOT NULL,
  feasible INTEGER NOT NULL,
  score_total REAL,
  score_breakdown TEXT,
  explanation TEXT,
  version INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS audit_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  actor TEXT NOT NULL,
  action TEXT NOT NULL,
  payload TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT
);
"""


@contextmanager
def connect():
    """Connection context manager that always commits and closes.

    Closing matters on Windows: an open handle blocks file replacement between
    test runs and dataset reloads.
    """
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(force: bool = False) -> None:
    if force and os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    with connect() as conn:
        conn.executescript(SCHEMA)


def get_meta(key: str, default: str = "") -> str:
    with connect() as conn:
        row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_meta(key: str, value: str) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value)),
        )


def schedule_version() -> int:
    return int(get_meta("version", "1") or 1)


def bump_version() -> int:
    v = schedule_version() + 1
    set_meta("version", v)
    return v


def get_policy() -> Dict[str, float]:
    raw = get_meta("policy", "")
    if raw:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
    return {
        "disruption": 0.30,
        "faculty": 0.20,
        "room": 0.15,
        "continuity": 0.20,
        "margin": 0.15,
    }


def set_policy(policy: Dict[str, float]) -> Dict[str, float]:
    clean = {k: max(0.0, float(v)) for k, v in policy.items() if k in
             {"disruption", "faculty", "room", "continuity", "margin"}}
    total = sum(clean.values()) or 1.0
    clean = {k: round(v / total, 4) for k, v in clean.items()}
    set_meta("policy", json.dumps(clean))
    return clean


# --------------------------------------------------------------------- seeding
def seed_from_payload(payload: Dict[str, Any]) -> None:
    """Replace the term data with the supplied dataset."""
    with connect() as conn:
        for table in [
            "session_group",
            "session",
            "faculty_availability",
            "alternative",
            "conflict",
            "course",
            "student_group",
            "faculty",
            "room",
            "time_slot",
            "term",
        ]:
            conn.execute(f"DELETE FROM {table}")
        term = payload["term"]
        conn.execute(
            "INSERT INTO term(id,name,starts_on,ends_on) VALUES(1,?,?,?)",
            (term["name"], term["starts_on"], term["ends_on"]),
        )
        for s in payload["slots"]:
            conn.execute(
                "INSERT INTO time_slot(id,day,start_min,end_min,is_exam) VALUES(?,?,?,?,?)",
                (s["id"], s["day"], to_minutes(s["start"]), to_minutes(s["end"]), int(s.get("is_exam", False))),
            )
        for r in payload["rooms"]:
            conn.execute(
                "INSERT INTO room(id,code,capacity,kind,features) VALUES(?,?,?,?,?)",
                (r["id"], r["code"], r["capacity"], r["kind"], json.dumps(r.get("features", []))),
            )
        for f in payload["faculty"]:
            conn.execute(
                "INSERT INTO faculty(id,name,email,max_hours_week) VALUES(?,?,?,?)",
                (f["id"], f["name"], f.get("email"), f.get("max_hours_week", 18)),
            )
        for g in payload["groups"]:
            conn.execute(
                "INSERT INTO student_group(id,name,strength,programme,semester) VALUES(?,?,?,?,?)",
                (g["id"], g["name"], g["strength"], g.get("programme"), g.get("semester")),
            )
        for c in payload["courses"]:
            conn.execute(
                "INSERT INTO course(id,code,title,credits,required_features) VALUES(?,?,?,?,?)",
                (c["id"], c["code"], c["title"], c["credits"], json.dumps(c.get("required_features", []))),
            )
        for a in payload.get("availability", []):
            conn.execute(
                "INSERT INTO faculty_availability(faculty_id,day,start_min,end_min,kind) VALUES(?,?,?,?,?)",
                (
                    a["faculty_id"],
                    a["day"],
                    to_minutes(a["start"]),
                    to_minutes(a["end"]),
                    a.get("kind", "available"),
                ),
            )
        for s in payload["sessions"]:
            conn.execute(
                "INSERT INTO session(id,course_id,faculty_id,room_id,slot_id,kind,required_features,pinned,status)"
                " VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    s["id"],
                    s["course_id"],
                    s["faculty_id"],
                    s["room_id"],
                    s["slot_id"],
                    s.get("kind", "lecture"),
                    json.dumps(s.get("required_features", [])),
                    int(s.get("pinned", False)),
                    s.get("status", "scheduled"),
                ),
            )
            for gid in s.get("group_ids", []):
                conn.execute(
                    "INSERT INTO session_group(session_id,group_id) VALUES(?,?)", (s["id"], gid)
                )
        conn.execute("INSERT INTO meta(key,value) VALUES('version','1') "
                     "ON CONFLICT(key) DO UPDATE SET value='1'")
        conn.execute("INSERT INTO meta(key,value) VALUES('dataset_name',?) "
                     "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (term["name"],))


# ---------------------------------------------------------------------- loading
def load_context() -> Context:
    with connect() as conn:
        term_row = conn.execute("SELECT * FROM term LIMIT 1").fetchone()
        if term_row is None:
            raise RuntimeError("No data loaded. POST /api/seed or import a dataset first.")
        term = dict(term_row)
        slots = {
            r["id"]: Slot(r["id"], r["day"], r["start_min"], r["end_min"], bool(r["is_exam"]))
            for r in conn.execute("SELECT * FROM time_slot")
        }
        rooms = {
            r["id"]: Room(
                r["id"], r["code"], r["capacity"], r["kind"], frozenset(json.loads(r["features"] or "[]"))
            )
            for r in conn.execute("SELECT * FROM room")
        }
        faculty = {
            r["id"]: Faculty(r["id"], r["name"], r["max_hours_week"])
            for r in conn.execute("SELECT * FROM faculty")
        }
        groups = {
            r["id"]: Group(r["id"], r["name"], r["strength"], r["programme"] or "", r["semester"] or 1)
            for r in conn.execute("SELECT * FROM student_group")
        }
        courses = {
            r["id"]: Course(
                r["id"],
                r["code"],
                r["title"],
                r["credits"],
                frozenset(json.loads(r["required_features"] or "[]")),
            )
            for r in conn.execute("SELECT * FROM course")
        }
        session_groups: Dict[int, List[int]] = {}
        for r in conn.execute("SELECT session_id, group_id FROM session_group"):
            session_groups.setdefault(r["session_id"], []).append(r["group_id"])
        sessions = {}
        for r in conn.execute("SELECT * FROM session"):
            sessions[r["id"]] = Session(
                id=r["id"],
                course_id=r["course_id"],
                faculty_id=r["faculty_id"],
                room_id=r["room_id"],
                slot_id=r["slot_id"],
                kind=r["kind"],
                group_ids=session_groups.get(r["id"], []),
                required_features=frozenset(json.loads(r["required_features"] or "[]")),
                pinned=bool(r["pinned"]),
                status=r["status"],
            )
        availability = [
            {
                "faculty_id": r["faculty_id"],
                "day": r["day"],
                "start": r["start_min"],
                "end": r["end_min"],
                "kind": r["kind"],
            }
            for r in conn.execute("SELECT * FROM faculty_availability")
        ]
    day_cap = int(get_meta("day_load_cap", "5") or 5)
    return Context(slots, rooms, faculty, groups, courses, sessions, availability, term,
                   day_load_cap=day_cap, version=schedule_version())


# -------------------------------------------------------------------- mutations
def update_session_placement(session_id: int, room_id: int, slot_id: int, faculty_id: int) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE session SET room_id=?, slot_id=?, faculty_id=? WHERE id=?",
            (room_id, slot_id, faculty_id, session_id),
        )


def add_conflicts(conflicts: List[dict]) -> List[int]:
    ids = []
    with connect() as conn:
        conn.execute("DELETE FROM conflict WHERE status='open'")
        for c in conflicts:
            cur = conn.execute(
                "INSERT INTO conflict(code,constraint_id,severity,score,session_ids,entity_refs,message,status)"
                " VALUES(?,?,?,?,?,?,?,'open')",
                (
                    c["code"],
                    c.get("constraint", ""),
                    c["severity"],
                    c["score"],
                    json.dumps(c["session_ids"]),
                    json.dumps(c.get("entities", {})),
                    c["message"],
                ),
            )
            ids.append(cur.lastrowid)
    return ids


def list_conflicts(status: str = "open") -> List[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM conflict WHERE status=? ORDER BY score DESC, id DESC", (status,)
        ).fetchall()
    return [
        {
            "conflict_id": r["id"],
            "code": r["code"],
            "constraint": r["constraint_id"],
            "severity": r["severity"],
            "score": r["score"],
            "session_ids": json.loads(r["session_ids"]),
            "entities": json.loads(r["entity_refs"] or "{}"),
            "message": r["message"],
            "status": r["status"],
            "detected_at": r["detected_at"],
        }
        for r in rows
    ]


def get_conflict(conflict_id: int) -> Optional[dict]:
    rows = list_conflicts("open") + list_conflicts("resolved") + list_conflicts("ignored")
    for c in rows:
        if c["conflict_id"] == conflict_id:
            return c
    return None


def replace_alternatives(conflict_id: int, alternatives: List[dict], version: int) -> List[dict]:
    with connect() as conn:
        conn.execute("DELETE FROM alternative WHERE conflict_id=?", (conflict_id,))
        stored = []
        for a in alternatives:
            cur = conn.execute(
                "INSERT INTO alternative(conflict_id,strategy,patch,feasible,score_total,score_breakdown,"
                "explanation,version) VALUES(?,?,?,?,?,?,?,?)",
                (
                    conflict_id,
                    a["strategy"],
                    json.dumps(a["patch"]),
                    1 if a["feasible"] else 0,
                    a["score"]["total"],
                    json.dumps(a["score"]),
                    a["explanation"],
                    version,
                ),
            )
            a = dict(a)
            a["alternative_id"] = cur.lastrowid
            a["conflict_id"] = conflict_id
            stored.append(a)
    return stored


def get_alternative(alternative_id: int) -> Optional[dict]:
    with connect() as conn:
        r = conn.execute("SELECT * FROM alternative WHERE id=?", (alternative_id,)).fetchone()
    if r is None:
        return None
    return {
        "alternative_id": r["id"],
        "conflict_id": r["conflict_id"],
        "strategy": r["strategy"],
        "patch": json.loads(r["patch"]),
        "feasible": bool(r["feasible"]),
        "score": json.loads(r["score_breakdown"] or "{}"),
        "explanation": r["explanation"],
        "version": r["version"],
    }


def list_alternatives(conflict_id: int) -> List[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM alternative WHERE conflict_id=? ORDER BY score_total DESC", (conflict_id,)
        ).fetchall()
    return [
        {
            "alternative_id": r["id"],
            "conflict_id": r["conflict_id"],
            "strategy": r["strategy"],
            "patch": json.loads(r["patch"]),
            "feasible": bool(r["feasible"]),
            "score": json.loads(r["score_breakdown"] or "{}"),
            "explanation": r["explanation"],
            "version": r["version"],
        }
        for r in rows
    ]


def resolve_conflict(conflict_id: int, status: str = "resolved") -> None:
    with connect() as conn:
        conn.execute("UPDATE conflict SET status=? WHERE id=?", (status, conflict_id))


def audit(actor: str, action: str, payload: dict) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO audit_log(actor,action,payload,created_at) VALUES(?,?,?,?)",
            (actor, action, json.dumps(payload), datetime.now(timezone.utc).isoformat(timespec="seconds")),
        )


def list_audit(limit: int = 50) -> List[dict]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [
        {
            "id": r["id"],
            "actor": r["actor"],
            "action": r["action"],
            "payload": json.loads(r["payload"] or "{}"),
            "created_at": r["created_at"],
        }
        for r in rows
    ]


def snapshot() -> dict:
    """Compact snapshot of all session placements (used for rollback/diff)."""
    with connect() as conn:
        rows = conn.execute("SELECT id,room_id,slot_id,faculty_id FROM session").fetchall()
    return {str(r["id"]): [r["room_id"], r["slot_id"], r["faculty_id"]] for r in rows}


def restore(snap: dict) -> None:
    with connect() as conn:
        for sid, (room_id, slot_id, faculty_id) in snap.items():
            conn.execute(
                "UPDATE session SET room_id=?, slot_id=?, faculty_id=? WHERE id=?",
                (room_id, slot_id, faculty_id, int(sid)),
            )
