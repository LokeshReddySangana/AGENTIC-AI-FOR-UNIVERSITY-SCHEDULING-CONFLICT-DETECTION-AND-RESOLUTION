"""Training pipeline for the supervised random-forest model.

Labels come from recorded scheduler behaviour. Because a fresh install has no
decision history, the pipeline bootstraps a balanced training set from the
institutional scoring policy (a documented proxy for past decisions) with
label noise, then adds every repair the scheduler actually applies as an
additional positive example.

Only supervised learning is used: there is no clustering, no anomaly detection
and no dimensionality reduction anywhere in this package.
"""
from __future__ import annotations

import os
import random
import statistics
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from ..constraints import validate_placement
from ..models import Context, Placement, ScheduleView
from ..scoring.criteria import DEFAULT_POLICY, evaluate_patch, total_score
from .features import FEATURE_LABELS, FEATURES, extract
from .forest import RandomForest

MODEL_PATH = os.environ.get(
    "SCHED_MODEL",
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "data",
        "model.json",
    ),
)

HYPERPARAMETERS = {
    "n_estimators": 80,
    "max_depth": 7,
    "min_samples_leaf": 6,
    "n_thresholds": 10,
    "seed": 2026,
}

_cache: Dict[str, object] = {}


def _sample_patch(ctx: Context, session_id: int, rng: random.Random) -> Optional[List[dict]]:
    """Draw a plausible alternative placement for one session."""
    session = ctx.sessions[session_id]
    slots = [s for s in ctx.slots.values() if (s.is_exam == (session.kind == "exam"))]
    if not slots:
        return None
    slot = rng.choice(slots)
    rooms = [
        r for r in ctx.rooms.values()
        if r.capacity >= ctx.enrolment(session)
        and (session.kind != "lab" or r.kind == "lab")
        and set(session.required_features) <= set(r.features)
    ]
    if not rooms:
        return None
    room = rng.choice(rooms)
    faculty = session.faculty_id
    if len(ctx.faculty) > 1 and rng.random() < 0.25:
        faculty = rng.choice([f for f in ctx.faculty if f != faculty])
    return [
        {"session_id": session_id, "slot_id": slot.id, "room_id": room.id, "faculty_id": faculty}
    ]


def build_dataset(ctx: Context, sample_count: int = 700, seed: int = 2026,
                  noise: float = 0.07) -> Tuple[List[List[float]], List[int], List[dict]]:
    """Balanced bootstrap dataset labelled from the institutional policy."""
    rng = random.Random(seed)
    session_ids = [sid for sid in ctx.sessions if ctx.sessions[sid].status == "scheduled"]
    rows: List[Tuple[List[float], float, List[dict]]] = []
    attempts = 0
    while len(rows) < sample_count and attempts < sample_count * 30:
        attempts += 1
        sid = rng.choice(session_ids)
        patch = _sample_patch(ctx, sid, rng)
        if patch is None:
            continue
        p = patch[0]
        if (p["slot_id"], p["room_id"], p["faculty_id"]) == (
            ctx.sessions[sid].slot_id,
            ctx.sessions[sid].room_id,
            ctx.sessions[sid].faculty_id,
        ):
            continue
        # Train on the population the model scores at inference time:
        # placements that satisfy every hard constraint.
        view = ScheduleView(ctx, {sid: Placement(p["slot_id"], p["room_id"], p["faculty_id"])})
        if validate_placement(view, sid):
            continue
        score = total_score(evaluate_patch(ctx, patch), DEFAULT_POLICY)
        rows.append((extract(ctx, patch), score, patch))

    if not rows:
        return [], [], []

    threshold = statistics.median(r[1] for r in rows)
    X: List[List[float]] = []
    y: List[int] = []
    patches: List[dict] = []
    for vector, score, patch in rows:
        label = 1 if score >= threshold else 0
        if rng.random() < noise:  # label noise: real schedulers are inconsistent
            label = 1 - label
        X.append(vector)
        y.append(label)
        patches.append(patch)
    return X, y, patches


def train_model(ctx: Optional[Context] = None, positives: Optional[List[List[dict]]] = None) -> dict:
    """Fit the random forest, persist it, and return a training report."""
    if ctx is None:
        from .. import db

        ctx = db.load_context()

    X, y, _ = build_dataset(ctx)
    if not X:
        raise RuntimeError("no training data could be generated")

    for patch in positives or []:  # real approvals become additional positive examples
        try:
            X.append(extract(ctx, patch))
            y.append(1)
        except (KeyError, TypeError):
            continue

    split = int(len(X) * 0.8)
    X_train, y_train = X[:split], y[:split]
    X_test, y_test = X[split:], y[split:]

    model = RandomForest(**HYPERPARAMETERS).fit(X_train, y_train)
    metrics = model.evaluate(X_test, y_test)
    train_metrics = model.evaluate(X_train, y_train)

    importances = [
        {"feature": FEATURE_LABELS[name], "key": name, "importance": score}
        for name, score in zip(FEATURES, model.feature_importances)
    ]
    importances.sort(key=lambda d: d["importance"], reverse=True)

    trained_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    model.save(
        MODEL_PATH,
        extra={
            "metrics": metrics,
            "train_metrics": train_metrics,
            "n_train": len(X_train),
            "n_test": len(X_test),
            "trained_at": trained_at,
            "positive_rate": round(sum(y) / len(y), 3),
            "features": FEATURES,
            "importances_report": importances,
            "hyperparameters": HYPERPARAMETERS,
            "label_source": "bootstrap institutional policy + applied repairs",
        },
    )
    _cache.clear()
    return {
        "metrics": metrics,
        "train_metrics": train_metrics,
        "n_train": len(X_train),
        "n_test": len(X_test),
        "trained_at": trained_at,
        "positive_rate": round(sum(y) / len(y), 3),
        "importances": importances,
        "hyperparameters": HYPERPARAMETERS,
        "model_path": MODEL_PATH,
    }


def get_model() -> Optional[RandomForest]:
    """Load the persisted model (cached by file mtime)."""
    if not os.path.exists(MODEL_PATH):
        return None
    mtime = os.path.getmtime(MODEL_PATH)
    if _cache.get("mtime") == mtime:
        return _cache.get("model")  # type: ignore[return-value]
    model = RandomForest.load(MODEL_PATH)
    _cache["mtime"] = mtime
    _cache["model"] = model
    return model


def model_report() -> dict:
    model = get_model()
    if model is None:
        return {"trained": False}
    return {
        "trained": True,
        "type": "random forest (binary classification)",
        "metrics": getattr(model, "metrics", {}),
        "trained_at": getattr(model, "trained_at", ""),
        "n_train": getattr(model, "n_train", 0),
        "n_test": getattr(model, "n_test", 0),
        "features": FEATURE_LABELS,
        "importances": [
            {"feature": FEATURE_LABELS[name], "key": name, "importance": score}
            for name, score in zip(FEATURES, model.feature_importances)
        ],
        "hyperparameters": {
            "n_estimators": model.n_estimators,
            "max_depth": model.max_depth,
            "min_samples_leaf": model.min_samples_leaf,
            "seed": model.seed,
        },
    }


def ensure_model(ctx: Optional[Context] = None) -> None:
    """Train on first run so the dashboard always has a model."""
    if get_model() is None:
        try:
            train_model(ctx)
        except (RuntimeError, KeyError):
            pass
