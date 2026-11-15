"""Ranking, Pareto filtering and explanation generation."""
from __future__ import annotations

from typing import Dict, List

from ..ml.features import extract as extract_features
from ..ml.train import get_model
from ..models import Context
from .criteria import CRITERIA, DEFAULT_POLICY, evaluate_patch, total_score

# Weight of the supervised classifier in the blended recommendation score.
LEARNED_WEIGHT = 0.30

STRATEGY_LABELS = {
    "A1-time-shift": "time shift",
    "A2-room-change": "room change",
    "A3-faculty-substitution": "faculty substitution",
    "A1+A2": "time + room change",
    "A4-combined": "combined re-placement",
    "A6-linked-reshuffle": "linked-group re-shuffle",
}


def _pareto_flags(scored: List[dict]) -> List[bool]:
    flags = []
    for i, a in enumerate(scored):
        dominated = False
        for j, b in enumerate(scored):
            if i == j:
                continue
            better_or_equal = all(
                b["breakdown"][k] >= a["breakdown"][k] - 1e-9 for k in CRITERIA
            )
            strictly_better = any(
                b["breakdown"][k] > a["breakdown"][k] + 1e-9 for k in CRITERIA
            )
            if better_or_equal and strictly_better:
                dominated = True
                break
        flags.append(not dominated)
    return flags


def _fmt_time(ctx, slot_id: int) -> str:
    return ctx.slots[slot_id].label


def explain(ctx: Context, alt: dict, score: dict, rank: int) -> str:
    parts = []
    for p in alt["patch"]:
        sid = p["session_id"]
        old = ctx.sessions[sid]
        new_room = ctx.rooms[p["room_id"]]
        old_room = ctx.rooms[old.room_id]
        course = ctx.courses.get(old.course_id)
        code = course.code if course else f"session {sid}"
        groups = ", ".join(ctx.group_name(g) for g in old.group_ids) or "no group"
        students = sum(ctx.groups[g].strength for g in old.group_ids if g in ctx.groups)
        changes = []
        if p["slot_id"] != old.slot_id:
            changes.append(f"{_fmt_time(ctx, old.slot_id)} → {_fmt_time(ctx, p['slot_id'])}")
        if p["room_id"] != old.room_id:
            changes.append(f"{old_room.code} → {new_room.code}")
        if p["faculty_id"] != old.faculty_id:
            changes.append(
                f"instructor {ctx.faculty[old.faculty_id].name} → {ctx.faculty[p['faculty_id']].name}"
            )
        detail = "; ".join(changes) if changes else "no change"
        parts.append(
            f"{code} {old.kind} for {groups} ({students} students): {detail}. "
            f"{new_room.code} seats {new_room.capacity}."
        )

    b = score["breakdown"]
    strongest = max(CRITERIA, key=lambda k: b.get(k, 0.0))
    weakest = min(CRITERIA, key=lambda k: b.get(k, 0.0))
    label = STRATEGY_LABELS.get(alt["strategy"], alt["strategy"])
    learned = score.get("learned")
    learned_text = (
        f" The supervised model predicts a {learned * 100:.1f}% chance a scheduler accepts this repair."
        if learned is not None
        else ""
    )
    return (
        f"Option {rank} ({label}). " + " ".join(parts) +
        f" Policy score {score.get('rule_total', score['total']):.2f} — strongest on {strongest} "
        f"({b.get(strongest, 0):.2f}), weakest on {weakest} ({b.get(weakest, 0):.2f})."
        + learned_text
    )


def rank_alternatives(
    ctx: Context,
    alternatives: List[dict],
    policy: Dict[str, float] | None = None,
    learned_weight: float = LEARNED_WEIGHT,
) -> List[dict]:
    policy = policy or DEFAULT_POLICY
    model = get_model()
    seen = set()
    scored: List[dict] = []
    for alt in alternatives:
        if not alt.get("feasible"):
            continue
        key = tuple(sorted((p["session_id"], p["slot_id"], p["room_id"], p["faculty_id"]) for p in alt["patch"]))
        if key in seen:
            continue
        seen.add(key)
        breakdown = evaluate_patch(ctx, alt["patch"])
        rule_total = total_score(breakdown, policy)
        try:
            learned = model.predict_proba(extract_features(ctx, alt["patch"])) if model else None
        except (KeyError, TypeError):
            learned = None
        total = (
            round((1 - learned_weight) * rule_total + learned_weight * learned, 4)
            if learned is not None
            else rule_total
        )
        scored.append(
            {
                "strategy": alt["strategy"],
                "patch": alt["patch"],
                "feasible": True,
                "breakdown": breakdown,
                "score": {
                    "breakdown": breakdown,
                    "rule_total": rule_total,
                    "learned": learned,
                    "total": total,
                },
            }
        )

    scored.sort(key=lambda a: -a["score"]["total"])
    flags = _pareto_flags(scored)
    ranked = []
    for i, (alt, on_front) in enumerate(zip(scored, flags)):
        alt["score"]["pareto"] = on_front
        alt["score"]["total"] = alt["score"]["total"]
        alt["explanation"] = explain(ctx, alt, alt["score"], i + 1)
        ranked.append(alt)
    return ranked
