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

REPORTS = [
    ROOT / "evals/reports/2026-09-04-hosted-ladder.json",
    ROOT / "evals/reports/2026-09-07-hosted-ladder.json",
]
OUTPUT = ROOT / "config/shadow-model-rollout.json"


def build() -> dict:
    result = compare([load_report(p) for p in REPORTS], load_cases(), REMEDIATION)
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
        "evidence": {"independent_runs": len(REPORTS), "source_reports": [p.name for p in REPORTS]},
        "decision_rule": {
            "enable": "Safe in every shadow run, adequately sampled, and not dominated by rule code. Assisted pilot only; human approval remains required.",
            "keep-human-only": "Adequately sampled with no consistently safe candidate, or every case requires abstention.",
            "insufficient-evidence": "Under-sampled or inconsistent between shadow runs.",
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
