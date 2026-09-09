#!/usr/bin/env python3
"""Convert a Remediation Evals Kit report into ai-review-calibration.v1 records.

Offline and read-only. It writes JSON files; it never touches the database and never calls a
provider. Ingestion stays where it already is:

    # 1. convert (writes <out>/dataset-manifest.json and <out>/<version>.json per cohort)
    python scripts/evals_to_calibration.py evals/reports/2026-09-07-hosted-ladder.json \\
        --cases evals/cases --evaluated-at 2026-09-07T00:00:00Z \\
        --validator-version evals-graders.<12hex> --out out/calibration

    # 2. inspect what it would authorise, and what it would not
    python scripts/evals_to_calibration.py ... --shortfall

    # 3. ingest one cohort, through the operator seam that already exists
    python scripts/ingest_ai_review_calibration.py out/calibration/<version>.json \\
        --owner <owner> --dataset out/calibration/dataset-manifest.json \\
        --report evals/reports/2026-09-07-hosted-ladder.json --ingest

Read evals/calibration.py's module docstring before trusting a number this prints. The short
version: these records measure whether a fix VERIFIED, per (format, criterion, model). They do
not measure whether alt text is any good, they carry no second-model reviewer, and on the
repo's own generated corpus they are `synthetic` — which `applicable_evaluation` refuses as
production qualification, on purpose.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "api"))

from evals.calibration import (BridgeError, build_evaluations, canonical_bytes,  # noqa: E402
                               case_ids_covered, dataset_manifest,
                               refuse_repo_corpus_as_evaluated, sha256_file, shortfall_table,
                               validator_version)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("report", type=Path, help="an evals report JSON carrying `results` rows")
    ap.add_argument("--cases", type=Path, default=ROOT / "evals" / "cases",
                    help="the corpus the report was produced from (default: evals/cases)")
    ap.add_argument("--evaluated-at", required=True,
                    help="UTC timestamp of the RUN, e.g. 2026-09-07T00:00:00Z. Required and "
                         "never guessed: the report carries no timestamp, and a file mtime is "
                         "the checkout date, not the evaluation date")
    ap.add_argument("--validator-version", default=None,
                    help="the grader revision that produced this report. Defaults to a digest "
                         "of the graders in THIS tree, which is right only for a report you "
                         "just generated; pass the recorded value for a historical one")
    ap.add_argument("--version-prefix", default=None,
                    help="leading segment of evaluation_version (default: the report filename)")
    ap.add_argument("--kind", choices=("synthetic", "evaluated"), default="synthetic",
                    help="provenance kind. `evaluated` is refused for the repo's own generated "
                         "corpus; use it only for a representative real-content run")
    ap.add_argument("--minimum-samples", type=int, default=30,
                    help="the evidence policy this run is measured against "
                         "(remediation_impact_estimates.MINIMUM_SAMPLES)")
    ap.add_argument("--out", type=Path, default=None,
                    help="directory to write records into; omit to validate and report only")
    ap.add_argument("--shortfall", action="store_true",
                    help="print the per-cohort sample shortfall table")
    args = ap.parse_args()

    try:
        refuse_repo_corpus_as_evaluated(args.cases, args.kind)
        report = json.loads(args.report.read_text())
        manifest = dataset_manifest(args.cases)
        missing = case_ids_covered(report, manifest)
        if missing:
            raise BridgeError(
                f"{len(missing)} case id(s) graded in the report are absent from --cases "
                f"({', '.join(missing[:5])}{'…' if len(missing) > 5 else ''}). The corpus and "
                "the report disagree, so the dataset digest would commit to the wrong bytes.")
        manifest_bytes = canonical_bytes(manifest)
        result = build_evaluations(
            report,
            report_sha256=sha256_file(args.report),
            dataset_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
            evaluated_at=args.evaluated_at,
            validator=args.validator_version or validator_version(),
            version_prefix=args.version_prefix or args.report.stem,
            kind=args.kind,
            minimum_samples=args.minimum_samples,
        )
    except BridgeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    # Validate through the contract's own validator, never a copy of its rules. A record that
    # this refuses is a bug in the bridge, and it should surface here rather than at 3am in an
    # operator's ingest.
    from ai_review_calibration import normalize_evaluation
    for record in result["records"]:
        try:
            normalize_evaluation(record)
        except ValueError as e:
            print(f"error: {record['evaluation_version']}: {e}", file=sys.stderr)
            return 2

    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "dataset-manifest.json").write_bytes(manifest_bytes)
        for record in result["records"]:
            (args.out / f"{record['evaluation_version']}.json").write_bytes(canonical_bytes(record))

    census = result["census"]
    print(json.dumps({"validated": len(result["records"]), "written": bool(args.out),
                      "census": census}, indent=2))
    if args.shortfall:
        print()
        print(f"{'cohort':52} {'n':>4} {'pass':>5} {'cases':>6} {'reps':>5} {'need reps':>10}")
        for row in shortfall_table(result, minimum_samples=args.minimum_samples):
            print(f"{row['cohort']:52} {row['samples']:>4} {row['passed']:>5} "
                  f"{row['cases']:>6} {row['repeats']:>5} "
                  f"{(row['repeats_required'] if row['short_by'] else '-'):>10}")
    if census["cohorts_meeting_minimum"] == 0 and census["cohorts"]:
        print(f"\nnote: 0 of {census['cohorts']} cohorts reach the {census['minimum_samples']}-sample "
              f"evidence policy (largest is {census['largest_cohort']}). Every record here is "
              "valid and immutable; none of them authorises anything yet.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
