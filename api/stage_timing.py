"""Per-stage timing for the assessment pipeline (ADR 0037 Step 0 — measure FIRST).

Answers "where does a scan spend its time?" — download (I/O) vs analyse (CPU + GPU) — so the later
Track B worker-count decisions are made from DATA, not guesses. This module is PURE accumulation +
aggregation; the wiring (handlers._analyse_and_persist_one) records around the real stage boundaries.

It only MEASURES. No behaviour change, and — the load-bearing property — a timing failure can never
touch the scan it measures: every function here is total (no raises on bad input), and the caller wraps
recording in best-effort guards.
"""
from __future__ import annotations

import time
from contextlib import contextmanager

# The coarse stages a per-file assessment passes through today, in display order. Deliberately the two
# that are cleanly separable in the current (flat) pipeline; ADR 0037's later steps split `analyse` into
# extract / checks / vision as each is pulled into its own bounded pool, and this list grows with them.
STAGES = ("download", "analyse")


class ScanTimings:
    """Accumulates per-stage total seconds + call counts. ONE instance per per-file job (not shared
    across threads); the per-scan rollup is the merge of all of them (see `merge_rollups`)."""

    def __init__(self):
        self.totals: dict[str, float] = {}
        self.counts: dict[str, int] = {}

    @contextmanager
    def stage(self, name: str):
        """Time the wrapped block into `name`. Uses a monotonic clock (immune to wall-clock jumps), and
        records in a `finally` so an exception in the block is still measured, then re-raised."""
        t0 = time.monotonic()
        try:
            yield
        finally:
            dt = time.monotonic() - t0
            self.totals[name] = self.totals.get(name, 0.0) + dt
            self.counts[name] = self.counts.get(name, 0) + 1

    def add(self, name: str, seconds) -> None:
        """Record a raw duration — for a call site where the `with` form would force awkward
        re-indentation of an existing try/except (as in the fan-out per-file path). Total: a bad or
        negative value is dropped, never raised, so timing can never disturb the code it measures."""
        try:
            s = float(seconds)
        except (TypeError, ValueError):
            return
        if s < 0:
            return
        self.totals[name] = self.totals.get(name, 0.0) + s
        self.counts[name] = self.counts.get(name, 0) + 1

    def as_dict(self) -> dict:
        return {
            "totals_s": {k: round(v, 4) for k, v in self.totals.items()},
            "counts": dict(self.counts),
        }


def merge_rollups(rollups) -> dict:
    """Combine many per-file `ScanTimings.as_dict()` into one per-scan rollup — sum totals + counts per
    stage. Skips falsy/malformed entries rather than raising: a timing merge must never fail a scan."""
    totals: dict[str, float] = {}
    counts: dict[str, int] = {}
    for r in rollups or []:
        if not isinstance(r, dict):
            continue
        for k, v in (r.get("totals_s") or {}).items():
            try:
                totals[k] = totals.get(k, 0.0) + float(v)
            except (TypeError, ValueError):
                continue
        for k, v in (r.get("counts") or {}).items():
            try:
                counts[k] = counts.get(k, 0) + int(v)
            except (TypeError, ValueError):
                continue
    return {"totals_s": {k: round(v, 4) for k, v in totals.items()}, "counts": counts}


def bottleneck(rollup) -> str | None:
    """The stage that consumed the most total time — the one ADR 0037 says to tune first. None when
    nothing was measured, so a caller shows '—' rather than inventing a bottleneck."""
    totals = (rollup or {}).get("totals_s") or {}
    live = {k: v for k, v in totals.items() if isinstance(v, (int, float)) and v > 0}
    return max(live, key=live.get) if live else None


def summarize(rollup) -> dict:
    """A read-ready view: the merged totals/counts, the bottleneck stage, and per-stage average seconds
    (total / count) — the number that actually says whether a stage is slow, versus merely frequent."""
    rollup = rollup or {}
    totals = rollup.get("totals_s") or {}
    counts = rollup.get("counts") or {}
    avg = {}
    for k, t in totals.items():
        c = counts.get(k, 0)
        avg[k] = round(t / c, 4) if c else 0.0
    return {"totals_s": totals, "counts": counts, "avg_s": avg, "bottleneck": bottleneck(rollup)}
