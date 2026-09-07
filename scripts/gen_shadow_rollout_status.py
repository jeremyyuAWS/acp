"""Generate the compact, runtime-safe shadow-model rollout report used by Settings.

The large source reports remain eval artifacts. Production receives only this derived JSON:
the declared verdict, its evidence, and aggregate candidate observations per category.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "api")]

from evals.schema import load_cases  # noqa: E402
from evals.shadow_lane import compare, load_report  # noqa: E402
from remediation_capability import REMEDIATION  # noqa: E402

# The 142-case corpus: every (format, criterion) has at least two cases, so no category is
# withheld for under-sampling. This is ONE run, where the previous pair was two runs on the
# 100-case corpus — coverage bought at the cost of replication, and `evidence` below says so.
# The comparison refuses to pool reports from different corpora, so this is a switch, not an
# addition; the two 100-case reports stay committed and are still read by
# scripts/shadow_lane_comparison.py.
REPORTS = [
    ROOT / "evals/reports/2026-09-07-hosted-ladder-142.json",
]
OUTPUT = ROOT / "config/shadow-model-rollout.json"


def candidate_safety(reports: list[dict]) -> list[dict]:
    """Per candidate, corpus-wide: the gates it passed and the violations it recorded.

    A per-category "enable" row cannot show this, and without it the panel would recommend a
    tier while hiding that the same tier wrote outside scope somewhere else in the same run.
    On the 142-case run Sonnet is the enable candidate for five categories AND recorded one
    critical violation on docx:1.1.1; both facts belong on the same screen.
    """
    out = []
    for rep in reports:
        for c in rep["candidates"]:
            if not c["candidate"].startswith("anthropic:"):
                continue
            m = c["metrics"]
            out.append({
                "candidate": c["candidate"],
                "critical_violations": m["critical_violations"],
                "autonomous_precision": m["autonomous_precision"],
                "abstention_correctness": m["abstention_correctness"],
                "varr": m["varr"],
                "gates_failed": [g["name"] for g in c["gates"] if not g["passed"]],
            })
    return out


def build() -> dict:
    reports = [load_report(p) for p in REPORTS]
    result = compare(reports, load_cases(), REMEDIATION)
    rows = []
    for row in result["rows"]:
        candidates = []
        for name, evidence in row["claude"].items():
            candidates.append({
                "candidate": name,
                "safe_runs": sum(bool(v) for v in evidence["safe"]),
                "runs": len(evidence["safe"]),
                "mean_varr": evidence["mean_varr"],
                "mean_usd_per_case": evidence["mean_usd_per_case"],
            })
        rows.append({k: row[k] for k in (
            "category", "format", "criterion", "current_lane", "cases", "eligible",
            "must_abstain", "runs", "verdict", "why", "enable_candidate"
        )} | {"candidates": candidates})
    return {
        "schema_version": 1,
        "evidence": {
            "independent_runs": len(REPORTS),
            "source_reports": [p.name for p in REPORTS],
            "corpus_cases": result["corpus_cases"],
            "replication": ("Single run: a verdict here rests on one observation of each "
                            "category, not on agreement between runs."
                            if len(REPORTS) == 1 else
                            f"{len(REPORTS)} runs: a verdict requires the tier to be safe in "
                            f"every one of them."),
        },
        # Lanes the product actions that this run never saw (the table moved after it ran).
        # Shown so the panel cannot present a partial table as a complete one.
        "unmeasured_categories": result["unmeasured_categories"],
        "candidate_safety": candidate_safety(reports),
        "decision_rule": {
            "enable": "Safe in every shadow run, adequately sampled, and not dominated by rule code; where more than one tier is safe the cheapest by measured cost is named. Assisted pilot only; human approval remains required.",
            "keep-human-only": "Adequately sampled with no consistently safe candidate, or every case requires abstention.",
            "insufficient-evidence": "Fewer cases than the ladder will route on, or safe in some runs and not others. With a single source run only the case count can trigger this.",
            "no-change-rule-code": "Deterministic rule code is safe in every run and remains the lower-cost choice.",
        },
        "summary_categories": result["summary_categories"],
        "summary_cases": result["summary_cases"],
        "rows": rows,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    rendered = json.dumps(build(), indent=2, sort_keys=True) + "\n"
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text() != rendered:
            print(f"{OUTPUT.relative_to(ROOT)} is stale; run {Path(__file__).name}")
            return 1
        print("shadow-model rollout report is current")
        return 0
    OUTPUT.write_text(rendered)
    print(OUTPUT.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
