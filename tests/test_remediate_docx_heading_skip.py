"""Round-trip for the docx 2.4.6 heading-skip remediator (office_structure detector).

DOCX_HEADING_SKIP (2.4.6) is declared fix_mode='auto' and detected by
office_structure.docx_checks, but had no remediator — so it never cleared and was
routed to the HITL human lane. This builds a doc with a skipped heading level
(Heading 1 → Heading 3), remediates it, and re-scans with the SAME python detector,
asserting 0 residual. Needs only python-docx (no .NET CLI), since this SC is a
python-side check.
"""
from __future__ import annotations
import sys
from pathlib import Path

import pytest

pytest.importorskip("docx")
from docx import Document  # noqa: E402

ACP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ACP / "api"))

import office_structure as osx      # noqa: E402
import remediate_office as R        # noqa: E402


def _heading_skip_findings(path: Path):
    return [f for f in osx.docx_checks(path) if f["ruleId"] == "DOCX_HEADING_SKIP"]


def test_docx_heading_skip_clears_2_4_6(tmp_path):
    d = Document()
    d.add_heading("Overview", level=1)
    d.add_paragraph("Some intro text with enough words to be a real paragraph.")
    d.add_heading("Deep detail", level=3)          # skips Heading 2 → 2.4.6 failure
    d.add_paragraph("More body text under the deep detail heading here.")
    src = tmp_path / "skip.docx"
    d.save(src)

    assert _heading_skip_findings(src), "fixture should trip DOCX_HEADING_SKIP"

    fixed, applied, _skipped = R.remediate_office(src)
    assert fixed is not None
    assert any("2.4.6" in a for a in applied), f"expected a 2.4.6 change: {applied}"
    assert _heading_skip_findings(Path(fixed)) == [], "2.4.6 should clear on re-scan"


def test_docx_valid_outline_untouched(tmp_path):
    d = Document()
    d.add_heading("Overview", level=1)
    d.add_heading("Section", level=2)
    d.add_heading("Subsection", level=3)
    src = tmp_path / "ok.docx"
    d.save(src)

    assert not _heading_skip_findings(src)
    fixed, applied, _skipped = R.remediate_office(src)
    # A gap-free outline must not draw a spurious 2.4.6 change …
    assert not any("2.4.6" in a for a in applied)
    # … and must still re-scan clean.
    assert _heading_skip_findings(Path(fixed or src)) == []
