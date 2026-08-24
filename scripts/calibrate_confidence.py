#!/usr/bin/env python3
"""P4.6 — Empirical calibration of model-reported confidence scores.

THE PROBLEM. A local model that outputs `{"suggestion": "...", "confidence": 0.97}` is not
claiming a calibrated probability. It is reporting a token logit pattern that *looks like* high
confidence but has no demonstrated relationship to empirical precision. Using 0.97 as a gate —
"auto-apply when confidence ≥ 0.95" — without measuring what 0.95 actually predicts is the
same error as trusting an unchecked assertion.

WHAT THIS SCRIPT MEASURES. Given a set of model outputs tagged with:
  - the model's self-reported confidence (0–1)
  - the model's predicted verdict (PASS or FAIL)
  - the ground-truth verdict (from the labeled corpus or a human reviewer)

it groups predictions into confidence buckets and computes empirical precision per bucket.
Precision is computed SEPARATELY for PASS and FAIL predictions, because the two errors have
asymmetric costs:

    false PASS (model says PASS, truth is FAIL) — the document ships with a violation.
                The downstream cost is borne by a screen-reader user, not by a reviewer.
    false FAIL (model says FAIL, truth is PASS) — a compliant finding gets flagged.
                The downstream cost is a reviewer's time.

A gate on confidence makes sense only for auto-apply (Group A SCs under ADR 0041), where
false PASS is the category that bypasses human review. FAIL predictions always reach a human
reviewer, so their threshold is less critical — but it still matters for routing efficiency.

THE SAMPLE-SIZE CAVEAT (P4.2). Each bucket needs its own n before a precision claim means
anything. The rule of three says: with n_pass predictions in a bucket and zero false PASSes
observed, the 95% upper bound on the true false-PASS rate is 3/n_pass. To claim ≤ 1% false
PASS at 95% confidence you need 300 observations with zero false PASSes in that bucket —
pooling across buckets or across criteria overstates the evidence (see P4.2 docstring for the
independence argument). The table below shows the bound per bucket and the n needed to clear
a 1% gate.

WHAT IS NOT INCLUDED HERE. Model-reported confidence does not currently exist as a structured
field in ACP's model outputs — `suggest_fix()` returns text, not JSON with a confidence key.
This script is the measurement instrument for when confidence elicitation is added. The input
schema below is what a future bench or prompt-engineering pass would need to produce.

Item schema (JSON array):
    {
        "model":          "qwen2.5vl:7b",      # required
        "criterion":      "2.4.4",             # required — WCAG SC
        "confidence":     0.92,                # required — model's self-reported confidence [0,1]
        "model_verdict":  "PASS",              # required — model's predicted verdict
        "truth_verdict":  "FAIL",              # required — ground-truth verdict
        "draft":          "Click here"         # optional — the proposed value
    }

Run:
    python scripts/calibrate_confidence.py --input ~/Downloads/acp-eval/confidence_items.json
    python scripts/calibrate_confidence.py --demo          # synthetic illustrative data
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

# Confidence buckets: variable-width, densest near the top where gates live.
# Each tuple is (lo_inclusive, hi_exclusive).
BUCKETS: list[tuple[float, float]] = [
    (0.50, 0.70),
    (0.70, 0.80),
    (0.80, 0.90),
    (0.90, 0.95),
    (0.95, 1.01),   # 1.01 so conf=1.0 falls in this bucket
]

VERDICTS = ("PASS", "FAIL")


def _bucket_label(lo: float, hi: float) -> str:
    hi_disp = "1.00" if hi > 1.0 else f"{hi:.2f}"
    return f"[{lo:.2f}, {hi_disp})"


def _assign_bucket(conf: float) -> int | None:
    for i, (lo, hi) in enumerate(BUCKETS):
        if lo <= conf < hi:
            return i
    return None


def _rule_of_three_bound(n_pass_preds: int, n_false_pass: int) -> str:
    """95% upper bound on true false-PASS rate."""
    if n_pass_preds == 0:
        return "  N/A"
    if n_false_pass == 0:
        bound = 3.0 / n_pass_preds
        return f"≤{bound:.1%}"
    return f"{n_false_pass / n_pass_preds:.1%}"


def _n_to_clear(target_rate: float = 0.01) -> int:
    """Observations needed in a bucket to claim ≤target_rate false-PASS at 95% confidence."""
    return math.ceil(3.0 / target_rate)


def calibrate(items: list[dict]) -> dict:
    """Compute per-(criterion, bucket) calibration statistics.

    Returns a nested dict:
        {criterion: {bucket_idx: {n_pass, n_false_pass, n_fail, n_false_fail, ...}}}
    """
    stats: dict[str, dict[int, dict]] = {}
    skipped = 0
    for it in items:
        criterion = it.get("criterion", "?")
        conf = it.get("confidence")
        mv = it.get("model_verdict", "").upper()
        tv = it.get("truth_verdict", "").upper()

        if conf is None or mv not in VERDICTS or tv not in VERDICTS:
            skipped += 1
            continue
        bi = _assign_bucket(conf)
        if bi is None:
            skipped += 1
            continue

        sc = stats.setdefault(criterion, {})
        b = sc.setdefault(bi, {"n_pass_pred": 0, "n_false_pass": 0,
                                "n_fail_pred": 0, "n_false_fail": 0})
        if mv == "PASS":
            b["n_pass_pred"] += 1
            if tv == "FAIL":
                b["n_false_pass"] += 1
        else:
            b["n_fail_pred"] += 1
            if tv == "PASS":
                b["n_false_fail"] += 1

    return stats, skipped


def _pass_precision(b: dict) -> float | None:
    n = b["n_pass_pred"]
    return None if n == 0 else (n - b["n_false_pass"]) / n


def _fail_precision(b: dict) -> float | None:
    n = b["n_fail_pred"]
    return None if n == 0 else (n - b["n_false_fail"]) / n


def _print_table(stats: dict, criteria_order: list[str] | None = None) -> None:
    criteria = criteria_order or sorted(stats)
    n_to_gate = _n_to_clear(0.01)

    for criterion in criteria:
        sc = stats.get(criterion)
        if not sc:
            continue
        print(f"\n=== {criterion} ===")
        print(f"{'bucket':<16} {'n_pass':>7} {'PASS prec':>10} {'false-PASS bound':>18} "
              f"{'n_fail':>7} {'FAIL prec':>10}")
        print("-" * 72)

        any_gap = False
        for i, (lo, hi) in enumerate(BUCKETS):
            b = sc.get(i)
            if b is None:
                continue
            label = _bucket_label(lo, hi)
            pp = _pass_precision(b)
            fp_bound = _rule_of_three_bound(b["n_pass_pred"], b["n_false_pass"])
            flp = _fail_precision(b)

            pp_str = f"{pp:.1%}" if pp is not None else "    N/A"
            flp_str = f"{flp:.1%}" if flp is not None else "    N/A"
            warn = " **" if b["n_false_pass"] > 0 else ""

            print(f"{label:<16} {b['n_pass_pred']:>7} {pp_str:>10} {fp_bound:>18}{warn}"
                  f" {b['n_fail_pred']:>7} {flp_str:>10}")

            if b["n_pass_pred"] > 0 and b["n_pass_pred"] < n_to_gate:
                shortage = n_to_gate - b["n_pass_pred"]
                any_gap = True
                print(f"  └─ need {shortage} more PASS predictions in this bucket "
                      f"to claim ≤1% false-PASS at 95% confidence (rule of three: 3/n)")

        if any_gap:
            print()

    print(f"\n** = false PASS observed (model_verdict=PASS, truth_verdict=FAIL)")
    print(f"false-PASS bound: ≤X% = rule-of-three 95% upper bound when no false PASS observed; "
          f"X% = measured rate otherwise")
    print(f"to gate auto-apply at ≤1% false PASS: need {n_to_gate} PASS predictions per bucket "
          f"with zero false PASSes observed")


def _demo_data() -> list[dict]:
    """Synthetic data illustrating a typical overconfident model.

    A well-calibrated model's false-PASS rate in the [0.95,1.0) bucket would be ≤5%. A typical
    LLM is overconfident: it reports 97% confidence while being wrong ~15% of the time on PASS
    predictions. This is the pattern this calibration tool is designed to catch.
    """
    import random
    rng = random.Random(42)
    items = []
    # (bucket_midpoint, true_false_pass_rate, true_false_fail_rate, n)
    profile = [
        (0.60, 0.30, 0.25, 25),   # low conf: ~calibrated, often wrong
        (0.75, 0.25, 0.20, 40),   # overconfident by ~10pp
        (0.85, 0.18, 0.14, 50),   # overconfident by ~18pp below stated
        (0.92, 0.14, 0.10, 60),   # 92% stated, ~86% actual PASS precision
        (0.97, 0.13, 0.08, 45),   # 97% stated, ~87% actual — the dangerous gap
    ]
    for criterion in ("2.4.4", "3.1.2"):
        for (mid, fp_rate, ff_rate, n) in profile:
            bi = _assign_bucket(mid)
            lo = BUCKETS[bi][0]
            hi = BUCKETS[bi][1]
            for _ in range(n):
                conf = rng.uniform(lo, min(hi, 1.0))
                # Model predicts PASS ~60% of the time
                mv = "PASS" if rng.random() < 0.60 else "FAIL"
                if mv == "PASS":
                    tv = "FAIL" if rng.random() < fp_rate else "PASS"
                else:
                    tv = "PASS" if rng.random() < ff_rate else "FAIL"
                items.append({"model": "demo-model", "criterion": criterion,
                              "confidence": round(conf, 3), "model_verdict": mv,
                              "truth_verdict": tv})
    return items


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    grp = ap.add_mutually_exclusive_group(required=True)
    grp.add_argument("--input", type=Path,
                     help="JSON array of calibration items (see item schema in module docstring)")
    grp.add_argument("--demo", action="store_true",
                     help="run on synthetic data illustrating a typical overconfident model")
    ap.add_argument("--out", type=Path,
                    help="write per-(criterion,bucket) stats as JSON")
    args = ap.parse_args()

    if args.demo:
        items = _demo_data()
        print("NOTE: demo mode — synthetic data, not real model outputs")
        print("A well-calibrated model would show false-PASS bound ≤ stated (1-confidence).")
        print("This demo shows a typical overconfident model: stated 97%, actual ~87% PASS prec.\n")
    else:
        p = args.input.resolve()
        items = json.loads(p.read_text())
        print(f"loaded {len(items)} items from {p}")

    stats, skipped = calibrate(items)
    if skipped:
        print(f"skipped {skipped} items (missing/invalid confidence, model_verdict, or "
              f"truth_verdict field)", file=sys.stderr)

    if not stats:
        print("no scoreable items — check that confidence, model_verdict and truth_verdict "
              "fields are present and valid")
        return 1

    total = len(items) - skipped
    criteria = sorted(stats)
    print(f"\nitems scored: {total}   criteria: {', '.join(criteria)}")
    print("\nASYMMETRIC COST REMINDER: false PASS bypasses human review (screen-reader safety).")
    print("false FAIL wastes reviewer time. Gate thresholds should reflect this asymmetry.\n")
    _print_table(stats)

    if args.out:
        out_doc = {
            "n_items": total,
            "n_skipped": skipped,
            "buckets": [_bucket_label(lo, hi) for lo, hi in BUCKETS],
            "per_criterion": {
                criterion: {
                    _bucket_label(*BUCKETS[i]): {
                        "n_pass_pred":   b["n_pass_pred"],
                        "n_false_pass":  b["n_false_pass"],
                        "pass_precision": _pass_precision(b),
                        "n_fail_pred":   b["n_fail_pred"],
                        "n_false_fail":  b["n_false_fail"],
                        "fail_precision": _fail_precision(b),
                    }
                    for i, b in sc.items()
                }
                for criterion, sc in stats.items()
            },
        }
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(out_doc, indent=2) + "\n")
        print(f"\nwrote {args.out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
