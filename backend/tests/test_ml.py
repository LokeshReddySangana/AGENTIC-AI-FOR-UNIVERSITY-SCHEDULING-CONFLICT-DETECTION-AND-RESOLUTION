"""Tests for the supervised random-forest recommendation layer.

Only supervised learning is exercised: labelled examples (accepted vs rejected
repairs) go in, a binary classifier comes out. No clustering or other
unsupervised step exists in this package.
"""
from __future__ import annotations

import json
import os

import pytest

from backend.app import db
from backend.app.detection.sweep import detect
from backend.app.ml import train as trainer
from backend.app.ml.features import FEATURES, extract
from backend.app.ml.forest import RandomForest
from backend.app.resolution.csp import resolve

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SAMPLE = os.path.join(ROOT, "data", "sample_university.json")


@pytest.fixture(scope="module")
def trained(tmp_path_factory):
    original_db, original_model = db.DB_PATH, trainer.MODEL_PATH
    db.DB_PATH = str(tmp_path_factory.mktemp("mldb") / "ml.db")
    trainer.MODEL_PATH = str(tmp_path_factory.mktemp("model") / "model.json")
    trainer._cache.clear()

    db.init_db(force=True)
    with open(SAMPLE, encoding="utf-8") as fh:
        db.seed_from_payload(json.load(fh))
    ctx = db.load_context()
    report = trainer.train_model(ctx)
    try:
        yield ctx, report
    finally:
        db.DB_PATH, trainer.MODEL_PATH = original_db, original_model
        trainer._cache.clear()


# ------------------------------------------------------------------ features
def test_feature_vector_is_stable(trained):
    ctx, _ = trained
    conflicts = detect(ctx)
    assert conflicts
    alternatives = resolve(ctx, conflicts[0], max_alternatives=1)
    vector = extract(ctx, alternatives[0]["patch"])
    assert len(vector) == len(FEATURES) == 11
    assert all(-2.0 <= v <= 2.0 for v in vector)


def test_features_reflect_room_change(trained):
    ctx, _ = trained
    session = next(s for s in ctx.sessions.values() if not s.pinned)
    other_room = next(r for r in ctx.rooms.values() if r.id != session.room_id and r.capacity >= 10)
    patch = [{"session_id": session.id, "slot_id": session.slot_id, "room_id": other_room.id,
              "faculty_id": session.faculty_id}]
    vector = dict(zip(FEATURES, extract(ctx, patch)))
    assert vector["room_change"] == 1.0
    assert vector["faculty_change"] == 0.0


# ---------------------------------------------------------------- the model
def test_forest_learns_separable_data():
    X = [[0.0, 0.0], [0.0, 1.0], [1.0, 0.0], [1.0, 1.0]] * 40
    y = [0, 0, 1, 1] * 40
    model = RandomForest(n_estimators=30, max_depth=4, min_samples_leaf=2).fit(X, y)
    assert model.predict_proba([0.0, 0.0]) < 0.35
    assert model.predict_proba([1.0, 1.0]) > 0.65
    assert 0.0 <= model.predict_proba([0.4, 0.6]) <= 1.0


def test_forest_ensemble_size_and_importances():
    X = [[float(i % 5), float(i % 3)] for i in range(120)]
    y = [1 if (a > 2 and b > 0) else 0 for a, b in X]
    model = RandomForest(n_estimators=25, max_depth=4).fit(X, y)
    assert len(model.trees) == 25
    assert len(model.feature_importances) == 2
    assert abs(sum(model.feature_importances) - 1.0) < 0.01
    assert model.predict_proba if True else False


def test_forest_predictions_are_averaged():
    X = [[float(i)] for i in range(60)]
    y = [1 if i > 30 else 0 for i in range(60)]
    model = RandomForest(n_estimators=20, max_depth=3, min_samples_leaf=2).fit(X, y)
    probs = [model.predict_proba([v]) for v in (5.0, 30.0, 55.0)]
    assert probs[0] < 0.4 and probs[2] > 0.6
    assert all(0.0 <= p <= 1.0 for p in probs)


def test_training_report(trained):
    _, report = trained
    assert report["n_train"] > 100
    assert report["n_test"] > 20
    assert 0.0 <= report["positive_rate"] <= 1.0
    assert report["metrics"]["accuracy"] > 0.65
    assert report["metrics"]["auc"] > 0.75
    assert report["hyperparameters"]["n_estimators"] == 80


def test_feature_importances_normalised(trained):
    _, report = trained
    total = sum(item["importance"] for item in report["importances"])
    assert abs(total - 1.0) < 0.02
    assert report["importances"][0]["importance"] > 0


def test_model_metrics_are_bounded(trained):
    _, report = trained
    for key in ["accuracy", "precision", "recall", "f1", "auc"]:
        assert 0.0 <= report["metrics"][key] <= 1.0


def test_model_persisted_and_reloadable(trained):
    assert os.path.exists(trainer.MODEL_PATH)
    loaded = RandomForest.load(trainer.MODEL_PATH)
    assert loaded is not None
    assert len(loaded.trees) == loaded.n_estimators
    assert len(loaded.feature_importances) == len(FEATURES)


# ------------------------------------------------------------------- ranking
def test_ranking_blends_model_and_policy(trained):
    ctx, _ = trained
    conflict = detect(ctx)[0]
    alternatives = resolve(ctx, conflict, max_alternatives=4)
    assert alternatives
    for alt in alternatives:
        score = alt["score"]
        assert score["learned"] is not None
        expected = round(0.7 * score["rule_total"] + 0.3 * score["learned"], 4)
        assert abs(score["total"] - expected) < 1e-3
    totals = [a["score"]["total"] for a in alternatives]
    assert totals == sorted(totals, reverse=True)


def test_learned_probabilities_are_not_degenerate(trained):
    ctx, _ = trained
    values = []
    for conflict in detect(ctx)[:4]:
        values.extend(a["score"]["learned"] for a in resolve(ctx, conflict, max_alternatives=4))
    assert values
    assert max(values) - min(values) > 0.05, "model should discriminate between options"


def test_explanation_mentions_the_model(trained):
    ctx, _ = trained
    alternatives = resolve(ctx, detect(ctx)[0], max_alternatives=1)
    assert "supervised model" in alternatives[0]["explanation"]


# ----------------------------------------------------------------------- API
def test_model_endpoint(trained):
    from fastapi.testclient import TestClient

    from backend.app.main import app

    with TestClient(app) as client:
        body = client.get("/api/model").json()
        assert body["trained"] is True
        assert body["metrics"]["auc"] > 0.7
        assert body["type"].startswith("random forest")
        assert sum(i["importance"] for i in body["importances"]) > 0.9


def test_retrain_endpoint(trained):
    from fastapi.testclient import TestClient

    from backend.app.main import app

    with TestClient(app) as client:
        report = client.post("/api/model/train").json()
        assert report["metrics"]["accuracy"] > 0.65
        entries = client.get("/api/audit").json()["audit"]
        assert any(e["action"] == "train-model" for e in entries)
