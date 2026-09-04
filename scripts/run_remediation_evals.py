#!/usr/bin/env python3
"""Run the Remediation Evals Kit and print the report.

    # the default run: no network, no cost, seconds
    python scripts/run_remediation_evals.py

    # a local model against the deterministic floor, three repeats
    python scripts/run_remediation_evals.py -c rules-only -c ollama:llama3.1:8b

    # any hosted endpoint, priced from the book in evals/cost.py
    python scripts/run_remediation_evals.py -c 'hosted:small-model@https://host/v1/chat/completions#hosted-nano'

    # CI: fail the build when a candidate stops clearing its gates
    python scripts/run_remediation_evals.py --fail-on-gate --json out/evals.json

The default candidate set is `rules-only` plus the scripted stubs, because a run that needs a
GPU is a run nobody makes, and the stubs are what prove the graders still bite.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from evals import candidates as cand      # noqa: E402
from evals.harness import run             # noqa: E402
from evals.report import Gates, build_report, render_markdown  # noqa: E402
from evals.schema import SUITES, load_cases                     # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-c", "--candidate", action="append", dest="candidates",
                    help="repeatable: rules-only | stub:good | ollama:<model> | "
                         "hosted:<model>@<url>[#price-tier]")
    ap.add_argument("--cases", default=str(ROOT / "evals" / "cases"))
    ap.add_argument("--suite", action="append", dest="suites", choices=list(SUITES))
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--repeats", type=int, default=3,
                    help="a single pass cannot tell 90%% accurate from 67%% (default: 3)")
    ap.add_argument("--no-cache", action="store_true",
                    help="price every call as if it were the first; the honest uncached figure")
    ap.add_argument("--max-usd-per-call", type=float, default=None,
                    help="budget gate (default 1e-5 = 0.001c = 100,000 calls per $1)")
    ap.add_argument("--min-varr", type=float, default=0.0)
    ap.add_argument("--json", dest="json_out", default=None)
    ap.add_argument("--md", dest="md_out", default=None)
    ap.add_argument("--fail-on-gate", action="store_true",
                    help="exit 1 if any candidate fails any gate")
    args = ap.parse_args()

    cases = load_cases(args.cases, suites=tuple(args.suites) if args.suites else None,
                       limit=args.limit)
    if not cases:
        print("no cases loaded", file=sys.stderr)
        return 2

    specs = args.candidates or ["rules-only", "stub:good", "stub:timid",
                                "stub:overeager", "stub:unsafe"]
    gates = Gates(**({"max_usd_per_call": args.max_usd_per_call}
                     if args.max_usd_per_call is not None else {}),
                  min_varr=args.min_varr)

    runs = []
    for spec in specs:
        try:
            candidate = cand.resolve(spec)
        except ValueError as e:
            print(f"skipping {spec}: {e}", file=sys.stderr)
            continue
        runs.append(run(candidate, cases, repeats=args.repeats, cache=not args.no_cache))

    if not runs:
        print("no candidates resolved", file=sys.stderr)
        return 2

    report = build_report(runs, cases, gates)
    md = render_markdown(report)
    print(md)

    if args.json_out:
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json_out).write_text(json.dumps(report, indent=2, default=str) + "\n")
    if args.md_out:
        Path(args.md_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.md_out).write_text(md + "\n")

    if args.fail_on_gate:
        failed = [r["candidate"] for r in report["candidates"]
                  if not all(g["passed"] for g in r["gates"])]
        if failed:
            print(f"\ngate failures: {', '.join(failed)}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
