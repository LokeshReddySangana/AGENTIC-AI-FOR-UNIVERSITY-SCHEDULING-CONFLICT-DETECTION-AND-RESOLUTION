"""Evaluation harness — numbers used in the project report.

Run: python -m backend.tools.benchmark
"""
from __future__ import annotations

import statistics
import time

from backend.app import db
from backend.app.detection.sweep import detect, detect_incremental
from backend.app.resolution.csp import resolve


def ms(fn, runs: int = 10):
    times = []
    for _ in range(runs):
        start = time.perf_counter()
        result = fn()
        times.append((time.perf_counter() - start) * 1000)
    return statistics.median(times), result


def main() -> None:
    ctx = db.load_context()
    print(f"Dataset: {ctx.term['name']} — {len(ctx.sessions)} sessions, "
          f"{len(ctx.rooms)} rooms, {len(ctx.faculty)} faculty, {len(ctx.groups)} groups\n")

    detect_ms, conflicts = ms(lambda: detect(ctx))
    print(f"Full detection            : {detect_ms:8.2f} ms  ({len(conflicts)} conflicts)")

    if conflicts:
        changed = conflicts[0]["session_ids"][:1]
        inc_ms, _ = ms(lambda: detect_incremental(ctx, changed), runs=20)
        print(f"Incremental detection     : {inc_ms:8.2f} ms  (1 changed session)")

    print("\n| conflict | code | alternatives | best score | time (ms) |")
    print("|---|---|---|---|---|")
    successes, times, counts = 0, [], []
    for index, conflict in enumerate(conflicts, start=1):
        start = time.perf_counter()
        alternatives = resolve(ctx, conflict)
        elapsed = (time.perf_counter() - start) * 1000
        if alternatives:
            successes += 1
            times.append(elapsed)
            counts.append(len(alternatives))
        best = f"{alternatives[0]['score']['total']:.3f}" if alternatives else "—"
        print(f"| {index} | {conflict['code']} | {len(alternatives)} | {best} | {elapsed:.1f} |")

    total = len(conflicts)
    print(f"\nRepair success rate       : {successes}/{total} = {100 * successes / max(total, 1):.0f}%")
    if times:
        print(f"Median repair time        : {statistics.median(times):.1f} ms")
        print(f"Median alternatives found : {statistics.median(counts):.0f}")


if __name__ == "__main__":
    main()
