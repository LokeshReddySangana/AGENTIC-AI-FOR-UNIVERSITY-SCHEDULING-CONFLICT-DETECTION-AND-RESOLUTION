"""Shared classification metrics (accuracy, precision, recall, F1, AUC, log-loss)."""
from __future__ import annotations

import math
from typing import Dict, Sequence


def classification_metrics(probs: Sequence[float], y: Sequence[int], threshold: float = 0.5) -> Dict[str, float]:
    preds = [1 if p >= threshold else 0 for p in probs]
    tp = sum(1 for p, t in zip(preds, y) if p == 1 and t == 1)
    tn = sum(1 for p, t in zip(preds, y) if p == 0 and t == 0)
    fp = sum(1 for p, t in zip(preds, y) if p == 1 and t == 0)
    fn = sum(1 for p, t in zip(preds, y) if p == 0 and t == 1)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    accuracy = (tp + tn) / max(len(y), 1)

    pos = [p for p, t in zip(probs, y) if t == 1]
    neg = [p for p, t in zip(probs, y) if t == 0]
    if pos and neg:
        wins = sum(1.0 if a > b else 0.5 if a == b else 0.0 for a in pos for b in neg)
        auc = wins / (len(pos) * len(neg))
    else:
        auc = 0.0

    eps = 1e-12
    log_loss = 0.0
    for p, t in zip(probs, y):
        p = min(1 - eps, max(eps, p))
        log_loss += -(t * math.log(p) + (1 - t) * math.log(1 - p))
    log_loss /= max(len(y), 1)

    return {
        "accuracy": round(accuracy, 3),
        "precision": round(precision, 3),
        "recall": round(recall, 3),
        "f1": round(f1, 3),
        "auc": round(auc, 3),
        "log_loss": round(log_loss, 3),
        "accuracy_on_rejects": round(tn / max(tn + fp, 1), 3),
        "accuracy_on_accepts": round(tp / max(tp + fn, 1), 3),
    }
