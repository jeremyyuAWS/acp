#!/usr/bin/env python3
"""Run the adversarial review-loop set and print the report.

    # the default run: no network, no cost, seconds — rules-only plus the scripted stubs
    python scripts/run_adversarial_claude_evals.py

    # Claude, priced from the book, three repeats, with a spend cap
    python scripts/run_adversarial_claude_evals.py --repeats 3 --max-spend-usd 1.00 \\
        -c rules-only -c anthropic:claude-haiku-4-5 -c anthropic:claude-sonnet-5

    # price it first
    python scripts/run_adversarial_claude_evals.py --estimate-only -c anthropic:claude-sonnet-5

Reports, per candidate and per category: accepted unchanged, accepted after editing, rejected
or refused (with the split), applied, cleared after re-scan, regressions introduced, latency and
cost. See docs/adversarial-claude-evals.md.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from evals import candidates as cand                                   # noqa: E402
from evals.cost import estimate_run_usd                                # noqa: E402
from evals.review import build_review_report, render_review_markdown, run_review  # noqa: E402
from evals.schema import CATEGORIES, load_cases                        # noqa: E402

CASES_DIR = ROOT / "evals" / "adversarial"
DEFAULT_CANDIDATES = ["rules-only", "stub:good", "stub:sloppy", "stub:literal", "stub:timid",
                      "stub:overeager", "stub:unsafe"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-c", "--candidate", action="append", dest="candidates",
                    help="repeatable: rules-only | stub:<name> | anthropic:<model>[#price-tier] | "
                         "ollama:<model> | hosted:<model>@<url>[#price-tier]")
    ap.add_argument("--cases", default=str(CASES_DIR))
    ap.add_argument("--category", action="append", dest="categories", choices=list(CATEGORIES))
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--repeats", type=int, default=3,
                    help="a single pass cannot tell a 90%% acceptance rate from 67%% (default: 3)")
    ap.add_argument("--no-cache", action="store_true",
                    help="price and time every call as if it were the first")
    ap.add_argument("--json", dest="json_out", default=None)
    ap.add_argument("--md", dest="md_out", default=None)
    ap.add_argument("--no-per-case", action="store_true", help="omit the per-case tables")
    ap.add_argument("--max-spend-usd", type=float, default=None,
                    help="refuse to start if the pre-flight estimate exceeds this")
    ap.add_argument("--estimate-only", action="store_true")
    ap.add_argument("--min-as-expected", type=float, default=None,
                    help="exit 1 if any candidate's as-expected rate is below this")
    args = ap.parse_args()

    cases = load_cases(args.cases, limit=None)
    if args.categories:
        cases = [c for c in cases if c.category in args.categories]
    if args.limit:
        cases = cases[:args.limit]
    if not cases:
        print("no cases loaded", file=sys.stderr)
        return 2

    resolved = []
    for spec in (args.candidates or DEFAULT_CANDIDATES):
        try:
            resolved.append(cand.resolve(spec))
        except ValueError as e:
            print(f"skipping {spec}: {e}", file=sys.stderr)
    if not resolved:
        print("no candidates resolved", file=sys.stderr)
        return 2

    calls = len(cases) * args.repeats
    total = 0.0
    print(f"pre-flight: {len(cases)} cases x {args.repeats} repeat(s) = {calls} calls per candidate",
          file=sys.stderr)
    for c in resolved:
        est = estimate_run_usd(c.pricing, calls)
        total += est
        print(f"  {c.name:34s} ~${est:,.4f}  ({c.pricing.kind}"
              f"{': ' + c.pricing.note if c.pricing.note else ''})  key: {c.key_source()}",
              file=sys.stderr)
    print(f"  {'TOTAL':34s} ~${total:,.4f}", file=sys.stderr)
    if args.estimate_only:
        return 0
    if args.max_spend_usd is not None and total > args.max_spend_usd:
        print(f"refusing to start: estimate ${total:,.4f} exceeds --max-spend-usd "
              f"${args.max_spend_usd:,.4f}", file=sys.stderr)
        return 2

    runs = [run_review(c, cases, repeats=args.repeats, cache=not args.no_cache) for c in resolved]
    report = build_review_report(runs, cases)
    md = render_review_markdown(report, per_case=not args.no_per_case)
    print(md)
    if args.json_out:
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json_out).write_text(json.dumps(report, indent=2, default=str) + "\n")
        print(f"wrote {args.json_out}", file=sys.stderr)
    if args.md_out:
        Path(args.md_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.md_out).write_text(md + "\n")
        print(f"wrote {args.md_out}", file=sys.stderr)

    if args.min_as_expected is not None:
        below = [r["candidate"] for r in report["candidates"]
                 if r["summary"]["rates"]["as_expected"] < args.min_as_expected]
        if below:
            print(f"below --min-as-expected {args.min_as_expected}: {', '.join(below)}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
