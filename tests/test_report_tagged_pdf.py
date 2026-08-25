"""P3.2 — ACP's own report PDF must pass its own pdf.tagged rule (WCAG 1.3.1).

reportlab cannot emit a PDF structure tree natively; _tag_pdf() post-processes
the output with pikepdf to inject the two entries the pdf.tagged detector requires:
  1. /Root/MarkInfo/Marked = true
  2. /Root/StructTreeRoot present

This fixture proves both conditions survive the full build_report() → _tag_pdf()
pipeline, using the same minimal fixture data the other report tests use.
"""
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))

_RUN = {"id": "s-tagged", "completed_at": "2026-08-25T00:00:00", "avg_score": 95,
        "owner_email": "test@example.com"}
_META = {"target": "AA", "version": "1.0", "hash": "abc123"}
_FILES = [{"file": "report.docx", "compliant": 1, "score": 100, "status": "pass", "issues": []}]
_FACTS = {
    "documents": [{"file": "report.docx", "evaluated": 5, "findings": 0,
                    "not_evaluated": 2, "remediated": 0, "remaining": 0, "approvals": 0,
                    "not_evaluated_criteria": [], "review_criteria": [],
                    "by_mode": {"auto": 5}}],
    "scope": {
        "catalog_size": 7, "by_mode": {"auto": 5},
        "not_evaluated_criteria": [], "review_criteria": [],
        "human_only_criteria": [], "formats_not_opened": [],
    },
    "remediated_total": 0,
    "approvals_total": 0,
    "review": {"reviewed": 0, "approved": 0, "rejected": 0, "skipped": 0},
}


def test_report_pdf_is_tagged():
    """build_report() output has MarkInfo.Marked=True and StructTreeRoot — passes pdf.tagged."""
    import pikepdf
    from report import build_report

    raw = build_report(_RUN, _FILES, _META, facts=_FACTS)
    assert isinstance(raw, bytes) and len(raw) > 0

    with pikepdf.open(io.BytesIO(raw)) as pdf:
        # Condition 1: /Root/MarkInfo/Marked must be true
        mark_info = pdf.Root.get("/MarkInfo")
        assert mark_info is not None, "/MarkInfo missing from /Root — pdf.tagged rule will fail"
        marked = mark_info.get("/Marked")
        assert marked == True, f"/MarkInfo/Marked is {marked!r}, expected true"  # noqa: E712

        # Condition 2: /Root/StructTreeRoot must be present
        struct_root = pdf.Root.get("/StructTreeRoot")
        assert struct_root is not None, "/StructTreeRoot missing from /Root — pdf.tagged rule will fail"
