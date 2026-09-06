#!/usr/bin/env python3
"""Generate the KEDA queue-scaler SQL, and fail the build when a deployed copy has drifted.

There are four scaler queries in this tree and none of them is where the truth lives:

    deploy/public/rightsize-production.sh   remediation-queue   depth, remediate lane
    deploy/public/rightsize-production.sh   assess-queue        depth, assess lane
    deploy/public/deploy.sh                 jobs-queued         depth, mixed tier (no lane filter)
    packaging/chart/acp/templates/…yaml     two triggers        depth + oldest-job-age, templated

`api/queue_scaler.py` owns the predicate; this script writes it out and, with `--check`, holds
those copies to it. The failure this exists to prevent is silent in both directions: a scaler
that counts jobs a worker cannot claim asks for replicas that idle, and a scaler that misses a
job type never asks for a replica at all. Neither raises anything. The only symptom is a tier
that scales for the wrong reason, or does not scale, and a queue that behaves as though the rule
were not there.

The type lists are already guarded — tests/test_packaging_chart.py reads api/core.py's own lane
tuples. What was NOT guarded, and was wrong in every copy until 2026-09-06, is the ELIGIBILITY
predicate: `store.claim_job` claims on status='queued' AND run_after <= now AND attempts <
max_attempts, and the queries tested only the first.

Usage:
    python scripts/gen_queue_scalers.py            # print the queries
    python scripts/gen_queue_scalers.py --check    # exit 1 if a deployed copy has drifted
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))

import core  # noqa: E402
import queue_scaler as qs  # noqa: E402

RIGHTSIZE = ROOT / "deploy/public/rightsize-production.sh"
DEPLOY = ROOT / "deploy/public/deploy.sh"
CHART = ROOT / "packaging/chart/acp/templates/autoscaling.yaml"


def queries() -> dict[str, str]:
    lanes = qs.lane_job_types()
    return {
        "rightsize:remediation-queue": qs.depth_query(lanes["remediate"]),
        "rightsize:assess-queue": qs.depth_query(lanes["assess"]),
        "deploy:jobs-queued": f"SELECT count(*) FROM jobs WHERE {qs.ELIGIBLE_SQL}",
        "chart:queue-depth": qs.depth_query(("<templated>",)),
        "chart:oldest-job-age": qs.oldest_age_query(("<templated>",)),
    }


def check() -> list[str]:
    """Every drift found, as messages. Empty means the deployed copies match.

    Returns rather than prints so the test that calls this reports the same text the CLI does.
    """
    problems: list[str] = []
    lanes = qs.lane_job_types()

    rightsize = RIGHTSIZE.read_text()
    for rule, lane in (("remediation-queue", "remediate"), ("assess-queue", "assess")):
        want = qs.depth_query(lanes[lane])
        if f'"query={want}"' not in rightsize:
            problems.append(
                f"{RIGHTSIZE.relative_to(ROOT)}: the {rule} rule does not carry the generated "
                f"query for the {lane} lane. Expected:\n    {want}")

    deploy = DEPLOY.read_text()
    if qs.ELIGIBLE_SQL not in deploy:
        problems.append(
            f"{DEPLOY.relative_to(ROOT)}: the jobs-queued rule does not carry the claim "
            f"predicate. Expected it to contain:\n    {qs.ELIGIBLE_SQL}")

    # The chart's query is a Go template, so the lane list cannot be compared literally — the
    # claimability half can, and it is the half that was missing. BOTH triggers, counted: the
    # oldest-job-age one is where an ineligible row does unbounded damage, and a fix applied to
    # the depth trigger alone would look done.
    chart = CHART.read_text()
    found = chart.count(qs.CLAIMABILITY_SQL)
    if found < 2:
        problems.append(
            f"{CHART.relative_to(ROOT)}: {found} of 2 triggers carry the claim predicate. Both "
            f"the queue-depth and oldest-job-age triggers must contain:\n    "
            f"{qs.CLAIMABILITY_SQL}")
    return problems


def main(argv: list[str]) -> int:
    if "--check" in argv:
        problems = check()
        for message in problems:
            print(f"drift: {message}", file=sys.stderr)
        if problems:
            print("\nRegenerate from api/queue_scaler.py, or run this script without --check to "
                  "see the expected queries.", file=sys.stderr)
            return 1
        print("queue scalers: every deployed copy matches api/queue_scaler.py")
        return 0
    for name, sql in queries().items():
        print(f"# {name}")
        print(sql)
        print()
    print(f"# lanes, from api/core.py: "
          f"{', '.join(f'{k}={len(v)} types' for k, v in qs.lane_job_types().items())}")
    print(f"# core.REMEDIATE_LANE_JOB_TYPES = {core.REMEDIATE_LANE_JOB_TYPES}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
