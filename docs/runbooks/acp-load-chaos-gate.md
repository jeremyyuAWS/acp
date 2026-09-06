# ACP multi-user Assess/Remediate load and chaos gate

This gate is the repeatable rehearsal for next week's multi-user testing. It models six tenants
submitting 24 scans containing 1,800 mixed DOCX, XLSX, PPTX, and PDF documents. Successful
assessments produce remediation work at the configured rate. Twelve workers claim work with
tenant-fair ordering while deterministic Redis, database, terminal, and mid-deploy interruption
faults exercise retries and dead letters.

It is an **isolated simulation**, not evidence that staging or production meets the SLO. Its job is
to keep the workload, metric definitions, fault shape, and go/no-go decision stable between test
runs. It imports no ACP service modules, accepts no URL or credentials, and cannot contact Azure,
Redis, PostgreSQL, or production.

## Run locally

From the repository root:

```bash
python3 -m performance.acp_load_gate \
  --scenario tests/load/scenarios/next_week_gate.json \
  --output performance-results/acp-load-chaos.json \
  --pretty
```

Exit `0` means `GO`, exit `1` means one or more thresholds produced `NO_GO`, and exit `2` means
the scenario is invalid. The output file is JSON with `schema_version`, `result`, `failures`, the
thresholds used, and all measured metrics. Use a fresh results path per staging rehearsal if the
team wants to retain a history; results are evidence and should not be hand-edited.

The committed deterministic baseline is `performance/results/next_week_baseline.json`. Regenerate
it after an intentional scenario or model change and review the delta.

Run the harness tests with:

```bash
pytest -q tests/load/test_acp_load_gate.py
```

## What is measured

- queue wait and execution p50/p95/p99/max, plus end-to-end p50/p95/p99/max;
- completed-job throughput and retry/dead-letter counts;
- Redis, database, and terminal error counts;
- per-tenant completed jobs, Jain's fairness index, and max/min completion ratio;
- jobs interrupted by the deploy window and how many eventually recovered.

Queue wait accumulates across attempts. Execution is the configured per-attempt service demand;
end-to-end spans enqueue to terminal completion. Throughput is completed jobs divided by scenario
elapsed time. A deploy event invalidates all active attempts, pauses claims for the configured
downtime, and requeues those jobs, which is the failure direction expected from a worker revision
turnover.

## Go/no-go policy

`tests/load/scenarios/next_week_gate.json` is the machine-readable source of truth. The baseline
gate requires:

| Signal | GO threshold |
|---|---:|
| Queue wait p95 | <= 300 s |
| End-to-end p99 | <= 420 s |
| Throughput | >= 4.2 completed jobs/s |
| Dead letters | <= 4 |
| Retries | <= 90 |
| Jain fairness | >= 0.995 |
| Max/min tenant completion ratio | <= 1.08 |
| Redis errors | <= 35 |
| Database errors | <= 55 |
| Deploy interruption recovery rate | 100% |

Any single breach is `NO_GO`; the JSON `failures` array names the metric, actual value, threshold,
operator, and reason. Do not average away a failed tail-latency, fairness, durability, or dependency
signal.

## Staging test procedure

1. Commit the exact scenario and record the application revision, worker counts, database tier,
   Redis tier, and test-host specification beside the result artifact.
2. Recreate the same tenant/scan/document mix through the approved staging load driver. Never aim
   this harness or an adapted driver at production.
3. Capture enqueue, claim, completion, retry, and dead-letter timestamps from the staging queue;
   dependency errors from staging telemetry; and worker revision changes during the controlled
   deploy window.
4. Normalize those observations to the JSON metric names above and evaluate the same thresholds.
5. Stop submissions if database or Redis safety limits are approached. A test must not change
   Azure capacity, production defaults, or deployment configuration to manufacture a pass.
6. Record `GO` only when every threshold passes. Attach the machine-readable result and environment
   record to the test evidence. A `NO_GO` requires an owner and rerun; it must not be waived by
   deleting the failed metric.

The committed baseline is deliberately `NO_GO`: its 368.5-second queue p95 and 445.8-second
end-to-end p99 exceed the next-week targets. A deterministic simulation that labels those tails
acceptable would make the gate green before the performance work it is meant to require. The
simulator proves that the scenario and decision logic are executable and deterministic; the
staging run remains required to validate real ACP queue, database, Redis, file-processing, and
deployment behavior.
