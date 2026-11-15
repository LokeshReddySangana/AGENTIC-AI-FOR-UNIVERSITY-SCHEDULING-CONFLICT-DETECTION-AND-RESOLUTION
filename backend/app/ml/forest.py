"""A compact random-forest classifier (supervised binary classification).

Written in plain Python so every tree, split and out-of-bag decision is
inspectable: bootstrap sampling, random feature subsets at each node, Gini
impurity splits, probability averaging across trees. No unsupervised step
exists anywhere in this module.
"""
from __future__ import annotations

import json
import math
import os
import random
from typing import Dict, List, Optional, Sequence

from .metrics import classification_metrics


class RandomForest:
    def __init__(
        self,
        n_estimators: int = 80,
        max_depth: int = 7,
        min_samples_leaf: int = 6,
        n_thresholds: int = 10,
        seed: int = 2026,
        smoothing: float = 1.0,
    ):
        self.n_estimators = n_estimators
        self.max_depth = max_depth
        self.min_samples_leaf = min_samples_leaf
        self.n_thresholds = n_thresholds
        self.seed = seed
        self.smoothing = smoothing
        self.trees: List[dict] = []
        self.feature_importances: List[float] = []

    # -------------------------------------------------------------- building
    def _gini(self, positives: int, total: int) -> float:
        if total <= 0:
            return 0.0
        p = positives / total
        return 2 * p * (1 - p)

    def _build(self, X, y, indices, depth, rng, importances) -> dict:
        n = len(indices)
        positives = sum(y[i] for i in indices)
        leaf = {
            "leaf": True,
            "p": round((positives + self.smoothing) / (n + 2 * self.smoothing), 5),
            "n": n,
        }
        if depth >= self.max_depth or n < 2 * self.min_samples_leaf or positives in (0, n):
            return leaf

        n_features = len(X[0])
        k = max(1, int(math.sqrt(n_features)))
        features = rng.sample(range(n_features), min(k, n_features))
        parent_gini = self._gini(positives, n)

        best = None  # (impurity, feature, threshold, left_idx)
        for f in features:
            values = sorted({X[i][f] for i in indices})
            if len(values) < 2:
                continue
            thresholds = set()
            for q in range(1, self.n_thresholds + 1):
                pos = int(round(q * (len(values) - 1) / (self.n_thresholds + 1)))
                pos = max(1, min(len(values) - 1, pos))
                thresholds.add((values[pos - 1] + values[pos]) / 2)
            for t in thresholds:
                left = [i for i in indices if X[i][f] <= t]
                if len(left) < self.min_samples_leaf or n - len(left) < self.min_samples_leaf:
                    continue
                left_pos = sum(y[i] for i in left)
                right_n = n - len(left)
                impurity = (
                    self._gini(left_pos, len(left)) * len(left)
                    + self._gini(positives - left_pos, right_n) * right_n
                ) / n
                if best is None or impurity < best[0]:
                    best = (impurity, f, t, left)

        if best is None:
            return leaf

        impurity, feature, threshold, left = best
        importances[feature] += (parent_gini - impurity) * n
        right = [i for i in indices if X[i][feature] > threshold]
        return {
            "leaf": False,
            "feature": feature,
            "threshold": round(threshold, 6),
            "p": leaf["p"],
            "left": self._build(X, y, left, depth + 1, rng, importances),
            "right": self._build(X, y, right, depth + 1, rng, importances),
        }

    def fit(self, X: Sequence[Sequence[float]], y: Sequence[int]) -> "RandomForest":
        rng = random.Random(self.seed)
        n = len(X)
        n_features = len(X[0])
        raw_importances = [0.0] * n_features
        self.trees = []
        for _ in range(self.n_estimators):
            sample = [rng.randrange(n) for _ in range(n)]  # bootstrap
            self.trees.append(self._build(X, y, sample, 0, rng, raw_importances))
        total = sum(raw_importances) or 1.0
        self.feature_importances = [round(v / total, 4) for v in raw_importances]
        return self

    # ------------------------------------------------------------- inference
    def _tree_proba(self, tree: dict, x: Sequence[float]) -> float:
        node = tree
        while not node["leaf"]:
            node = node["left"] if x[node["feature"]] <= node["threshold"] else node["right"]
        return node["p"]

    def predict_proba(self, x: Sequence[float]) -> float:
        if not self.trees:
            return 0.5
        return round(sum(self._tree_proba(t, x) for t in self.trees) / len(self.trees), 4)

    def predict(self, x: Sequence[float], threshold: float = 0.5) -> int:
        return 1 if self.predict_proba(x) >= threshold else 0

    def evaluate(self, X: Sequence[Sequence[float]], y: Sequence[int]) -> Dict[str, float]:
        return classification_metrics([self.predict_proba(row) for row in X], y)

    # ----------------------------------------------------------- persistence
    def to_dict(self) -> dict:
        return {
            "kind": "random_forest",
            "n_estimators": self.n_estimators,
            "max_depth": self.max_depth,
            "min_samples_leaf": self.min_samples_leaf,
            "n_thresholds": self.n_thresholds,
            "seed": self.seed,
            "feature_importances": self.feature_importances,
            "trees": self.trees,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "RandomForest":
        model = cls(
            n_estimators=data.get("n_estimators", 80),
            max_depth=data.get("max_depth", 7),
            min_samples_leaf=data.get("min_samples_leaf", 6),
            n_thresholds=data.get("n_thresholds", 10),
            seed=data.get("seed", 2026),
        )
        model.trees = data.get("trees", [])
        model.feature_importances = data.get("feature_importances", [])
        return model

    def save(self, path: str, extra: Optional[dict] = None) -> str:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        payload = self.to_dict()
        if extra:
            payload.update(extra)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
        return path

    @classmethod
    def load(cls, path: str) -> Optional["RandomForest"]:
        if not os.path.exists(path):
            return None
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        model = cls.from_dict(data)
        model.metrics = data.get("metrics", {})  # type: ignore[attr-defined]
        model.trained_at = data.get("trained_at", "")  # type: ignore[attr-defined]
        model.n_train = data.get("n_train", 0)  # type: ignore[attr-defined]
        model.n_test = data.get("n_test", 0)  # type: ignore[attr-defined]
        return model
