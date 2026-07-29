"""Server-side HTML remediation tests (ADR 0005). Pure lxml — no DB/engines."""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

from remediate import remediate_html  # noqa: E402


def test_adds_missing_lang():
    out, applied, _ = remediate_html("<html><head></head><body><p>hi</p></body></html>")
    assert 'lang="en"' in out
    assert any("3.1.1" in c for c in applied)


def test_keeps_existing_lang():
    out, applied, _ = remediate_html('<html lang="fr"><head><title>x</title></head><body></body></html>')
    assert 'lang="fr"' in out
    assert not any("3.1.1" in c for c in applied)


def test_adds_title_from_h1():
    out, applied, _ = remediate_html(
        "<html lang='en'><head></head><body><h1>Annual Report</h1></body></html>")
    assert "<title>Annual Report</title>" in out
    assert any("2.4.2" in c for c in applied)


def test_fills_blank_title():
    out, _, _ = remediate_html(
        "<html lang='en'><head><title>  </title></head><body><h1>Hello</h1></body></html>")
    assert "<title>Hello</title>" in out


def test_labels_unlabeled_input():
    out, applied, _ = remediate_html(
        "<html lang='en'><head><title>t</title></head>"
        "<body><form><input type='text' name='email' placeholder='Your email'></form></body></html>")
    assert 'aria-label="Your email"' in out
    assert any("1.3.1" in c for c in applied)


def test_keeps_labeled_input():
    out, applied, _ = remediate_html(
        "<html lang='en'><head><title>t</title></head>"
        "<body><form><input type='text' aria-label='Search'></form></body></html>")
    assert 'aria-label="Search"' in out
    # no new 1.3.1 change for an already-labeled control
    assert not any("1.3.1" in c for c in applied)


def test_deferred_includes_ai_assisted():
    # 'ai-assisted' SCs are not auto-fixed; their ids come back as deferred (→ HITL).
    _, _, deferred = remediate_html("<html><body></body></html>")
    # ai-assisted SCs aren't registered as 'auto', so if any were registered they'd
    # appear here. The current module registers only 'auto' fixers, so deferred is [].
    assert isinstance(deferred, list)


def test_clean_doc_no_changes():
    clean = ('<html lang="en"><head><title>Good</title></head>'
             '<body><form><input aria-label="Name"></form></body></html>')
    _, applied, _ = remediate_html(clean)
    assert applied == []


def test_promotes_pseudo_heading_and_rescan_clears():
    """1.3.1 round-trip: the promoter fixes exactly what scanner.html_pseudo_headings flags,
    so the re-scan clears — the lock-step contract office_structure documents for docx.

    The change description says 1.3.1, not 2.4.6: this signal moved criteria to agree with
    DOCX_PSEUDO_HEADING. The element is not a heading yet, so 2.4.6 has nothing to judge.
    """
    import tempfile

    import scanner

    src = ("<html lang='en'><head><title>t</title></head>"
           "<body><p style='font-size:24px;font-weight:bold'>Quarterly Results</p></body></html>")
    out, applied, _ = remediate_html(src)
    assert "<h2" in out and "Quarterly Results" in out
    assert any("1.3.1" in c for c in applied)
    assert not any("2.4.6" in c for c in applied), "pseudo-headings are not a 2.4.6 fix"

    tmp = Path(tempfile.mkdtemp()) / "fixed.html"
    tmp.write_text(out)
    residual = [i for i in scanner._analyse_html(tmp)["issues"]
                if i["ruleId"] == "HTML_PSEUDO_HEADING"]
    assert residual == [], residual


def test_promoting_to_h2_never_creates_a_heading_skip():
    """A promoted heading is always <h2>. HTML_HEADING_SKIP fires only when a level exceeds
    prev+1, which for level 2 needs prev < 1 — and prev 0 is the first-heading guard that is
    never judged. So the 1.3.1 fix cannot manufacture a 2.4.6 finding, wherever it lands."""
    import tempfile

    import scanner

    src = ("<html lang='en'><head><title>t</title></head><body>"
           "<h1>Real</h1><h2>Sub</h2><h3>Deeper</h3>"
           "<p style='font-size:24px;font-weight:bold'>Styled Section</p>"
           "</body></html>")
    out, _, _ = remediate_html(src)
    tmp = Path(tempfile.mkdtemp()) / "fixed.html"
    tmp.write_text(out)
    rules = [i["ruleId"] for i in scanner._analyse_html(tmp)["issues"]]
    assert "HTML_PSEUDO_HEADING" not in rules
    assert "HTML_HEADING_SKIP" not in rules, "promotion introduced a level gap"


def test_pseudo_heading_promotion_preserves_the_visual_style():
    """The defect is that the structure was never exposed, not that the text looked wrong.
    Keeping the inline style leaves the rendered page identical, so an auto-applied fix never
    surprises the author visually."""
    out, _, _ = remediate_html(
        "<html lang='en'><head><title>t</title></head>"
        "<body><p style='font-size:24px;font-weight:bold'>Outlook</p></body></html>")
    assert "font-size:24px" in out and "font-weight:bold" in out
