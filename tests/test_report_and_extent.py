"""Conformance report renders + physical file metadata extraction."""
from __future__ import annotations
import sys
import zipfile
from pathlib import Path

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))


def test_report_renders_pdf_with_charts():
    import report
    files = [
        {"file": "a.pdf", "status": "done", "compliant": 1, "score": 90, "skipped_rules": 0, "issues": []},
        {"file": "b.docx", "status": "done", "compliant": 0, "score": 55, "skipped_rules": 0,
         "issues": [{"wcag": "SC_1_1_1", "severity": "CRITICAL"}, {"wcag": "SC_2_4_2", "severity": "SERIOUS"}]},
        {"file": "c.html", "status": "error", "compliant": 0, "score": None, "skipped_rules": 0, "issues": []},
        {"file": "d.pptx", "status": "uncertain", "compliant": 0, "score": 70, "skipped_rules": 3, "issues": []},
    ]
    run = {"id": "t1", "completed_at": "2026-07-02T00:00:00", "avg_score": 72,
           "files": 4, "certifiable": 1, "uncertain": 1, "error": 1}
    pdf = report.build_report(run, files, {"target": "WCAG 2.1 Level AA", "version": "3", "hash": "abc"},
                              {"x": {"triage": "inscope", "action": {"state": "accepted"}}})
    assert pdf[:5] == b"%PDF-" and len(pdf) > 20_000   # logo embedded → non-trivial size


def test_report_status_matches_frontend_statusof():
    import report
    assert report._status({"status": "error", "compliant": 0}) == "unanalysable"
    assert report._status({"status": "uncertain", "compliant": 0}) == "uncertain"
    assert report._status({"status": "done", "compliant": 1}) == "certifiable"
    # 'issues' requires OPEN FINDINGS; a non-compliant file with none and a SCORE is 'clean'
    # (mirrors the frontend statusOf). Without a score it is 'not-assessed' — 'clean' asserts a
    # measurement, so it may not be inferred from the absence of one. See
    # tests/test_status_clean.py for the full matrix.
    assert report._status({"status": "done", "compliant": 0, "issues": [{"wcag": "1.1.1"}]}) == "issues"
    assert report._status({"status": "done", "compliant": 0, "issues": [], "score": 100}) == "clean"
    assert report._status({"status": "done", "compliant": 0, "issues": []}) == report.NOT_ASSESSED


def test_file_extent_size_and_ooxml_counts(tmp_path):
    from scanner import _file_extent
    txt = tmp_path / "x.html"
    txt.write_bytes(b"x" * 4096)
    assert _file_extent(txt, ".html") == {"size_kb": 4}

    pptx = tmp_path / "deck.pptx"
    with zipfile.ZipFile(pptx, "w") as z:
        for i in (1, 2, 3):
            z.writestr(f"ppt/slides/slide{i}.xml", "<x/>")
        z.writestr("ppt/slides/_rels/slide1.xml.rels", "<x/>")   # must not count
    out = _file_extent(pptx, ".pptx")
    assert out["pages"] == 3

    xlsx = tmp_path / "book.xlsx"
    with zipfile.ZipFile(xlsx, "w") as z:
        z.writestr("xl/worksheets/sheet1.xml", "<x/>")
        z.writestr("xl/worksheets/sheet2.xml", "<x/>")
    assert _file_extent(xlsx, ".xlsx")["sheets"] == 2


def test_file_extent_never_raises(tmp_path):
    from scanner import _file_extent
    corrupt = tmp_path / "bad.pdf"
    corrupt.write_bytes(b"not a pdf")
    out = _file_extent(corrupt, ".pdf")
    assert out.get("size_kb") == 1 and "pages" not in out
    assert _file_extent(tmp_path / "missing.pdf", ".pdf") == {}
