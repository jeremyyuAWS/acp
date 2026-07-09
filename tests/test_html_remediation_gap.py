"""Round-trip guarantee for the newly-ported deterministic HTML fixers
(1.3.5 / 1.4.1 / 2.4.1 / 2.4.3 / 2.4.6 / 2.4.7 / 2.5.3 / 3.1.4).

These SCs are declared fix_mode='auto' in RULE_CATALOG and are DETECTED by
scanner.py, but until now had no backend remediator — so after a remediate job
they never cleared and were routed to the HITL human lane as manual work. Each
test crafts HTML that trips exactly one detector, remediates it, then RE-SCANS
the output with the real scanner (scanner._analyse_html) and asserts the target
SC no longer appears. That is the honesty bar: a fix is only credited if the
same engine that flagged it reads it clean on re-scan (mirrors the runtime
verify-residual path in handlers._verify_residual_scs).
"""
from __future__ import annotations
import sys
import tempfile
from pathlib import Path

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

from remediate import remediate_html    # noqa: E402
import scanner                          # noqa: E402


def _roundtrip(html: str):
    """Return (fixed_html, applied_changes, residual_scs) after a real re-scan."""
    fixed, applied, _deferred = remediate_html(html)
    with tempfile.TemporaryDirectory(prefix="acp-gap-") as d:
        p = Path(d) / "f.html"
        p.write_text(fixed, encoding="utf-8")
        res = scanner._analyse_html(p)
    assert res["succeeded"], res.get("errors")
    scs = {i["wcag"].split()[0] for i in res["issues"]}
    return fixed, applied, scs


def _doc(body: str, head: str = "<title>T</title>") -> str:
    return f'<html lang="en"><head>{head}</head><body>{body}</body></html>'


def _applied_has(applied, sc):
    assert any(sc in a for a in applied), f"no applied change cites {sc}: {applied}"


def test_135_input_purpose_cleared():
    fixed, applied, scs = _roundtrip(_doc('<input type="email" aria-label="Email">'))
    assert 'autocomplete="email"' in fixed
    assert "1.3.5" not in scs
    _applied_has(applied, "1.3.5")


def test_135_derives_token_from_name():
    fixed, _a, scs = _roundtrip(_doc('<input aria-label="Zip" name="billing_postal_code">'))
    assert 'autocomplete="postal-code"' in fixed
    assert "1.3.5" not in scs


def test_141_use_of_color_cleared():
    fixed, applied, scs = _roundtrip(_doc('<a href="/x" style="color:#2E72C9">go</a>'))
    assert "text-decoration:underline" in fixed
    assert "1.4.1" not in scs
    _applied_has(applied, "1.4.1")


def test_141_replaces_text_decoration_none():
    fixed, _a, scs = _roundtrip(_doc('<a href="/x" style="color:red; text-decoration: none">go</a>'))
    assert "text-decoration:underline" in fixed and "none" not in fixed.split("text-decoration:underline")[0][-30:]
    assert "1.4.1" not in scs


def test_241_bypass_blocks_cleared():
    fixed, applied, scs = _roundtrip(_doc("<nav>menu</nav><p>real content</p>"))
    assert "<main" in fixed and 'id="main-content"' in fixed and "Skip to main content" in fixed
    assert "2.4.1" not in scs
    _applied_has(applied, "2.4.1")


def test_241_noop_without_chrome():
    _fixed, applied, scs = _roundtrip(_doc("<p>just content, no nav</p>"))
    assert not any("2.4.1" in a for a in applied)
    assert "2.4.1" not in scs


def test_243_focus_order_cleared():
    fixed, applied, scs = _roundtrip(_doc('<div tabindex="3">x</div>'))
    assert 'tabindex="0"' in fixed and 'tabindex="3"' not in fixed
    assert "2.4.3" not in scs
    _applied_has(applied, "2.4.3")


def test_246_heading_skip_cleared():
    fixed, applied, scs = _roundtrip(_doc("<h1>A</h1><h3>B</h3>"))
    assert "<h2>B</h2>" in fixed
    assert "2.4.6" not in scs
    _applied_has(applied, "2.4.6")


def test_246_leaves_valid_outline_alone():
    _fixed, applied, scs = _roundtrip(_doc("<h1>A</h1><h2>B</h2><h3>C</h3>"))
    assert not any("2.4.6" in a for a in applied)
    assert "2.4.6" not in scs


def test_247_focus_visible_cleared():
    fixed, applied, scs = _roundtrip(
        _doc('<a href="/x">link</a>', head='<title>T</title><meta name="viewport" content="width=device-width"><style>a{outline:none}</style>'))
    assert "outline:none" not in fixed and "outline:revert" in fixed
    assert "2.4.7" not in scs
    _applied_has(applied, "2.4.7")


def test_247_inline_suppression_cleared():
    fixed, _a, scs = _roundtrip(
        _doc('<a href="/x" style="outline:0">link</a>', head='<title>T</title><meta name="viewport" content="width=device-width">'))
    assert "outline:revert" in fixed
    assert "2.4.7" not in scs


def test_253_label_in_name_cleared():
    fixed, applied, scs = _roundtrip(_doc('<button aria-label="Submit">Send order</button>'))
    assert "2.5.3" not in scs
    assert 'aria-label="Send order' in fixed
    _applied_has(applied, "2.5.3")


def test_314_abbreviations_cleared():
    fixed, applied, scs = _roundtrip(_doc("<p>Please read the WCAG guidelines and the ADA rules.</p>"))
    assert '<abbr title="Web Content Accessibility Guidelines">WCAG</abbr>' in fixed
    assert '<abbr title="Americans with Disabilities Act">ADA</abbr>' in fixed
    assert "3.1.4" not in scs
    _applied_has(applied, "3.1.4")


def test_314_wraps_abbr_in_tail_text():
    # Abbreviation sitting in a child element's tail (after </b>) must also be wrapped.
    fixed, _a, scs = _roundtrip(_doc("<p><b>Note:</b> the PDF is attached</p>"))
    assert '<abbr title="Portable Document Format">PDF</abbr>' in fixed
    assert "3.1.4" not in scs


def test_314_idempotent_on_rerun():
    once, _a1, _s1 = _roundtrip(_doc("<p>Read the WCAG guidelines</p>"))
    twice, _applied2, scs2 = remediate_html(once)[0], *remediate_html(once)[1:]
    # A second pass must not double-wrap or re-flag.
    assert twice.count("<abbr") == once.count("<abbr")
    assert "3.1.4" not in scs2


def test_all_eight_scs_clear_in_one_document():
    """A single document tripping all eight new detectors re-scans clean for every one."""
    body = (
        '<nav>menu</nav>'
        '<h1>Title</h1><h3>Sub</h3>'
        '<a href="/a" style="color:#2E72C9">colour link</a>'
        '<button aria-label="Go">Place order</button>'
        '<input type="email" aria-label="Email">'
        '<div tabindex="5">panel</div>'
        '<p>About WCAG compliance</p>'
    )
    head = '<title>T</title><meta name="viewport" content="width=device-width"><style>:focus{outline:none}</style>'
    _fixed, _applied, scs = _roundtrip(_doc(body, head=head))
    for sc in ("1.3.5", "1.4.1", "2.4.1", "2.4.3", "2.4.6", "2.4.7", "2.5.3", "3.1.4"):
        assert sc not in scs, f"{sc} still failing after remediation; residual={sorted(scs)}"
