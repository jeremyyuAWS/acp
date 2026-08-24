"""Independent-verification steps (R13) + the POUR bar chart (R8 visual).

R13 is generic-per-format by design — it names a mainstream tool and the checks for each format
ACTUALLY in the scan, never a claim about a specific document — so the test asserts which formats
get a row, not doc-specific text. The POUR bars draw exactly the evaluated principles.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))


def _section(files):
    import report
    from reportlab.lib.styles import getSampleStyleSheet
    ss = getSampleStyleSheet()
    return report._manual_verification_section(files, ss["Heading2"], ss["BodyText"],
                                               ss["BodyText"], ss["BodyText"])


def _table_rows(els):
    from reportlab.platypus import Table
    t = next((e for e in els if isinstance(e, Table)), None)
    return None if t is None else t._cellvalues


def _cell_text(els):
    rows = _table_rows(els) or []
    out = []
    for r in rows:
        for c in r:
            out.append(str(getattr(c, "text", c)))
    return " ".join(out)


def test_only_formats_present_get_a_verification_row():
    els = _section([{"file": "a.docx"}, {"file": "b.pdf"}])
    rows = _table_rows(els)
    assert len(rows) == 3                              # header + Word + PDF
    txt = _cell_text(els)
    assert "Word" in txt and "PDF" in txt
    assert "Excel" not in txt and "PowerPoint" not in txt
    assert "NVDA" in txt or "VoiceOver" in txt          # the screen-reader path for PDF


def test_duplicate_format_collapses_to_one_row():
    els = _section([{"file": "a.docx"}, {"file": "b.docx"}, {"file": "c.docx"}])
    assert len(_table_rows(els)) == 2                   # header + one Word row


def test_no_known_format_renders_nothing():
    assert _section([{"file": "notes.txt"}]) == []
    assert _section([]) == []


def test_html_scans_get_a_verification_row():
    # P-1: HTML was missing from _MANUAL_VERIFY — HTML scans silently skipped the section.
    els = _section([{"file": "page.html"}, {"file": "doc.pdf"}])
    rows = _table_rows(els)
    assert rows is not None, "manual verification section rendered nothing for an HTML scan"
    labels = [str(getattr(r[0], "text", r[0])) for r in rows[1:]]   # skip header row
    assert any("HTML" in lbl for lbl in labels), "no HTML row in verification table"
    txt = _cell_text(els)
    assert "axe" in txt or "DevTools" in txt    # the recommended tool for HTML


# ── POUR bars ─────────────────────────────────────────────────────────────────

def test_pour_bars_draw_only_evaluated_principles():
    import report
    from reportlab.graphics.shapes import String
    principles = [
        {"principle": "Perceivable", "evaluated": 8, "passed": 6},
        {"principle": "Operable", "evaluated": 4, "passed": 4},
        {"principle": "Understandable", "evaluated": 0, "passed": 0},   # no bar
        {"principle": "Robust", "evaluated": 0, "passed": 0}]           # no bar
    d = report._pour_bars(principles)
    names = [s.text for s in d.contents if isinstance(s, String)]
    assert "Perceivable" in names and "Operable" in names
    assert "Understandable" not in names and "Robust" not in names     # 0-evaluated omitted
    assert any("6/8" in n for n in names)                              # the real rate is drawn
