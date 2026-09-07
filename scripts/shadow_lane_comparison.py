"""Compare shadow-mode Claude runs with the product's current remediation lane, per criterion.

    python scripts/shadow_lane_comparison.py \
        --report evals/reports/2026-09-04-hosted-ladder.json \
        --report evals/reports/2026-09-07-hosted-ladder.json \
        --md docs/remediation-evals-shadow-lane-comparison.md --json out/shadow-lane.json

Reads nothing but the committed JSON reports, the committed corpus and
`api/remediation_capability.REMEDIATION`. No network, no key, no cost — the paid runs it reads
were made by `scripts/run_remediation_evals.py`, in shadow, against the simulated executor.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "api"))

from evals.schema import load_cases                                   # noqa: E402
from evals.shadow_lane import compare, load_report, render_markdown   # noqa: E402
from remediation_capability import REMEDIATION                        # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--report", action="append", required=True,
                    help="repeatable: an evals JSON report from scripts/run_remediation_evals.py")
    ap.add_argument("--md", dest="md_out", default=None)
    ap.add_argument("--json", dest="json_out", default=None)
    ap.add_argument("--prefix", default="anthropic:",
                    help="candidate-name prefix that marks the shadow tier (default anthropic:)")
    args = ap.parse_args()

    reports = [load_report(p) for p in args.report]
    cmp = compare(reports, load_cases(), REMEDIATION, prefix=args.prefix)
    md = render_markdown(cmp)
    print(md)
    if args.md_out:
        Path(args.md_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.md_out).write_text(md)
    if args.json_out:
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json_out).write_text(json.dumps(cmp, indent=2, default=str) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
