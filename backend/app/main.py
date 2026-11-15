"""FastAPI application: REST API + static dashboard."""
from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import db
from .constraints import all_meta
from .constraints.soft import SOFT_WEIGHTS
from .detection.sweep import detect
from .models import ScheduleView
from .services import workflow

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SAMPLE = os.path.join(ROOT, "data", "sample_university.json")
FRONTEND = os.path.join(ROOT, "frontend")

@asynccontextmanager
async def lifespan(_: FastAPI):
    _seed_if_empty()
    from .ml.train import ensure_model

    ensure_model()
    yield


app = FastAPI(title="Scheduling Conflict Agent", version="1.0.0", lifespan=lifespan)


class Policy(BaseModel):
    disruption: float
    faculty: float
    room: float
    continuity: float
    margin: float


class MoveRequest(BaseModel):
    slot_id: int
    room_id: int
    faculty_id: int


class ApplyRequest(BaseModel):
    expected_version: Optional[int] = None
    actor: str = "scheduler"


def _seed_if_empty() -> None:
    db.init_db()
    try:
        db.load_context()
    except RuntimeError:
        if os.path.exists(SAMPLE):
            with open(SAMPLE, encoding="utf-8") as fh:
                db.seed_from_payload(json.load(fh))
            db.audit("system", "seed", {"dataset": "sample_university.json"})


# ----------------------------------------------------------------------- meta
@app.get("/api/health")
def health():
    return {"status": "ok", "version": db.schedule_version()}


@app.get("/api/constraints")
def constraints():
    return {
        "hard": all_meta(),
        "soft": SOFT_WEIGHTS,
        "policy": db.get_policy(),
    }


@app.get("/api/stats")
def stats():
    ctx = db.load_context()
    conflicts = detect(ctx)
    from .detection.sweep import summarise

    return {
        "sessions": len(ctx.sessions),
        "rooms": len(ctx.rooms),
        "faculty": len(ctx.faculty),
        "groups": len(ctx.groups),
        "courses": len(ctx.courses),
        "version": ctx.version,
        "conflicts": summarise(conflicts),
    }


# ----------------------------------------------------------------------- data
@app.post("/api/seed")
def seed_sample():
    if not os.path.exists(SAMPLE):
        raise HTTPException(404, "sample dataset missing")
    with open(SAMPLE, encoding="utf-8") as fh:
        db.seed_from_payload(json.load(fh))
    db.audit("system", "seed", {"dataset": "sample_university.json"})
    return {"seeded": True}


@app.post("/api/import")
def import_dataset(payload: dict = Body(...)):
    required = ["term", "slots", "rooms", "faculty", "groups", "courses", "sessions"]
    missing = [k for k in required if k not in payload]
    if missing:
        raise HTTPException(422, f"missing keys: {', '.join(missing)}")
    try:
        db.seed_from_payload(payload)
    except Exception as exc:  # noqa: BLE001 - surface import errors to the UI
        raise HTTPException(422, f"import failed: {exc}") from exc
    db.audit("scheduler", "import", {"sessions": len(payload["sessions"])})
    return {"imported": len(payload["sessions"])}


@app.get("/api/schedule")
def schedule():
    return workflow.schedule_view()


# ------------------------------------------------------------------ detection
@app.post("/api/detect")
def run_detection():
    return workflow.run_detection()


@app.get("/api/conflicts")
def conflicts(status: str = Query("open")):
    return {"conflicts": db.list_conflicts(status)}


@app.post("/api/conflicts/{conflict_id}/resolve")
def resolve(conflict_id: int, max_alternatives: int = Query(6, ge=1, le=20)):
    try:
        return workflow.resolve_conflict(conflict_id, max_alternatives)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.get("/api/conflicts/{conflict_id}/alternatives")
def alternatives(conflict_id: int):
    return {"alternatives": db.list_alternatives(conflict_id)}


@app.post("/api/alternatives/{alternative_id}/preview")
def preview(alternative_id: int):
    try:
        return workflow.preview_alternative(alternative_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.post("/api/alternatives/{alternative_id}/apply")
def apply(alternative_id: int, req: ApplyRequest = Body(default=ApplyRequest())):
    try:
        return workflow.apply_alternative(alternative_id, req.actor, req.expected_version)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/api/sessions/{session_id}/move")
def move(session_id: int, req: MoveRequest):
    try:
        result = workflow.move_session(session_id, req.slot_id, req.room_id, req.faculty_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    if not result.get("applied"):
        raise HTTPException(409, result)
    return result


# --------------------------------------------------------------------- policy
@app.get("/api/policy")
def get_policy():
    return db.get_policy()


@app.post("/api/policy")
def set_policy(policy: Policy):
    return db.set_policy(policy.model_dump())


@app.get("/api/model")
def model_info():
    from .ml.train import model_report

    return model_report()


@app.post("/api/model/train")
def retrain_model():
    """Retrain the supervised model, including every applied repair as a positive example."""
    from .ml.train import train_model

    ctx = db.load_context()
    positives = [
        entry["payload"]["patch"]
        for entry in db.list_audit(200)
        if entry["action"] in {"apply", "manual-move"} and entry["payload"].get("patch")
    ]
    report = train_model(ctx, positives=positives)
    db.audit("scheduler", "train-model", {"metrics": report["metrics"], "n_train": report["n_train"]})
    return report


@app.get("/api/audit")
def audit(limit: int = Query(50, ge=1, le=500)):
    return {"audit": db.list_audit(limit)}


@app.post("/api/rollback/{audit_id}")
def rollback(audit_id: int):
    entries = {a["id"]: a for a in db.list_audit(500)}
    entry = entries.get(audit_id)
    if entry is None:
        raise HTTPException(404, "audit entry not found")
    snap = entry["payload"].get("snapshot")
    if not snap:
        raise HTTPException(409, "no snapshot stored for this entry")
    db.restore(snap)
    version = db.bump_version()
    db.audit("scheduler", "rollback", {"audit_id": audit_id, "version": version})
    return {"rolled_back_to": version}


# ------------------------------------------------------------------------ UI
if os.path.isdir(FRONTEND):
    app.mount("/static", StaticFiles(directory=FRONTEND), name="static")

    @app.get("/")
    def index():
        return FileResponse(os.path.join(FRONTEND, "index.html"))
