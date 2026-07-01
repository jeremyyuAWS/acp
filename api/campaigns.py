"""Phased remediation campaign batch computation (ADR 0003, Phase 4).

Mirrors frontend/src/Monitor.jsx's useProgramBatches bucketing exactly (same four
buckets, same precedence: a file with any CRITICAL finding is bucket 1 regardless
of what else it has) -- this is the server-side, persisted version of that
client-derived view. Pure function, no DB access (api/store.py owns persistence,
same seam as api/documents.py and api/disposition.py).
"""
from __future__ import annotations

BUCKETS = ["critical", "serious", "moderate", "na"]

BUCKET_LABEL = {
    "critical": "Batch 1 · CRITICAL auto-fix",
    "serious": "Batch 2 · SERIOUS HITL review",
    "moderate": "Batch 3 · MODERATE sweep",
    "na": "N/A · excluded from plan",
}


def compute_batches(file_records: list[dict], severities_by_file: dict[str, set[str]]) -> list[dict]:
    """file_records: [{file, score, compliant}, ...] · severities_by_file: file -> set of
    severities seen for that file (from issue_records). Returns one dict per bucket with
    its member file list, in the same precedence order as the frontend: CRITICAL wins
    over SERIOUS wins over MODERATE; N/A is score>=90 with no CRITICAL/SERIOUS finding.
    """
    out: dict[str, list[str]] = {b: [] for b in BUCKETS}
    for rec in file_records:
        file = rec["file"]
        sev = severities_by_file.get(file, set())
        has_crit = "CRITICAL" in sev
        has_ser = "SERIOUS" in sev
        has_mod = "MODERATE" in sev
        score = rec.get("score")
        is_na = (score is not None and score >= 90) and not has_crit and not has_ser
        if has_crit:
            out["critical"].append(file)
        elif has_ser:
            out["serious"].append(file)
        elif has_mod:
            out["moderate"].append(file)
        elif is_na:
            out["na"].append(file)
        # files matching none of the above (e.g. no findings but score < 90, or no
        # score at all) aren't placed in any batch -- same as the frontend, which only
        # buckets files that hit one of these four conditions.
    return [{"bucket": b, "label": BUCKET_LABEL[b], "files": out[b], "count": len(out[b])} for b in BUCKETS]
