"""Public (unauthenticated) endpoints — R15 verify-this-report.

These routes are allowlisted in core.is_public() via the /public/ prefix and
require NO auth token. They must never return PII or document content — only
the machine-readable scan summary needed to recompute a report's content digest.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

import core

router = APIRouter(prefix="/public", tags=["public"])


@router.get("/verify/{scan_id}")
def verify_scan(scan_id: str):
    """Return the machine-readable scan summary for digest recomputation (R15).

    Allows an auditor — or anyone who received a PDF report — to:
      1. Fetch the canonical scan payload independently.
      2. Recompute the SHA-256 content digest printed in the report.
      3. Compare against the digest embedded in the PDF to detect alteration.

    Returns only aggregate compliance data (score, compliance flag, failing
    criteria per file). No document content, no filenames beyond what is in the
    report itself, no owner or email metadata.

    owner=None in get_scan() skips the per-user ownership check — this endpoint
    is intentionally readable by anyone who knows the scan ID, mirroring the
    public QR code in the PDF.

    Note on digest reproducibility: the digest includes the rubric's conformance
    target, which is read from the current active rubric. If the rubric's target
    changes between report export and verification, the digest will differ. Store
    the target alongside the scan if stricter reproducibility is required.
    """
    res = core.get_store().get_scan(scan_id, owner=None)
    if res is None:
        raise HTTPException(status_code=404, detail="Scan not found")

    run = res["run"]
    files = res["files"]

    # Build meta the same way the report_pdf route does so the digest is identical.
    rb = core.active_rubric()
    meta = {
        "target": rb.cfg.get("conformance_target"),
        "version": rb.version,
        "hash": run.get("rubric_hash") or rb.hash,
    }

    from report import _content_digest
    digest = _content_digest(run, files, meta)

    # The canonical payload mirrors what _content_digest() hashes — return it so
    # the caller can verify the digest without implementing the hash themselves.
    file_payloads = sorted(
        ({"file": f["file"],
          "score": f.get("score"),
          "compliant": int(bool(f.get("compliant"))),
          "failing": sorted({i.get("wcag", "") for i in (f.get("issues") or [])})}
         for f in files), key=lambda x: x["file"])

    return {
        "scan_id": run.get("id"),
        "digest": digest,
        "rubric_hash": meta["hash"],
        "target": meta["target"],
        "completed_at": run.get("completed_at"),
        "files": file_payloads,
    }
