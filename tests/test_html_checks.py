"""Backend _analyse_html unit tests for the checks ported from frontend rule
modules that previously had NO backend mirror at all (see api/scanner.py's
"Phase 4" comment block). Before this port, these SCs read as 'Shipped (demo)'
via their frontend module + the wcagCatalog contract test, but a real
server-side scan never checked them — every HTML file silently showed PASS.

1.4.4/1.4.10 are mutually exclusive on one document (no-viewport vs a viewport
that blocks zoom), so they're covered separately rather than forced into one
"kitchen sink" fixture — see test_scan.py's html-all-violations.html for the
10 that DO naturally coexist there.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

import scanner  # noqa: E402


def _scan(html: str):
    tmp = Path(tempfile.mkdtemp()) / "t.html"
    tmp.write_text(html)
    return scanner._analyse_html(tmp)


def _scs(result):
    return {i["wcag"] for i in result["issues"]}


def _fired(result, sc):
    return any(w.startswith(sc) for w in _scs(result))


def test_1_3_1_flags_form_control_with_no_accessible_name():
    r = _scan("<html><body><input type='text' name='x'></body></html>")
    assert _fired(r, "1.3.1")


def test_1_3_1_credits_implicit_label_wrapping_and_self_naming_types():
    r = _scan("""<html><body>
        <label>Name <input type="text"></label>
        <input type="hidden" name="csrf">
        <input type="submit" value="Go">
        </body></html>""")
    assert not _fired(r, "1.3.1")


def test_1_4_1_flags_link_colored_with_no_underline():
    r = _scan('<html><body><a href="#" style="color:#2E72C9">go</a></body></html>')
    assert _fired(r, "1.4.1")


def test_1_4_1_ignores_underlined_or_unstyled_links():
    r = _scan("""<html><body>
        <a href="#" style="color:red;text-decoration:underline">u</a>
        <a href="#">plain</a>
        </body></html>""")
    assert not _fired(r, "1.4.1")


def test_1_4_3_flags_light_inline_text_color():
    r = _scan('<html><body><p style="color:#cccccc">faint</p></body></html>')
    assert _fired(r, "1.4.3")


def test_1_4_3_ignores_dark_text():
    r = _scan('<html><body><p style="color:#222222">dark</p></body></html>')
    assert not _fired(r, "1.4.3")


def test_1_4_4_flags_viewport_that_blocks_zoom():
    r = _scan('<html><head><meta name="viewport" content="width=device-width, user-scalable=no">'
              '</head><body>x</body></html>')
    assert _fired(r, "1.4.4")


def test_1_4_4_ignores_a_normal_viewport():
    r = _scan('<html><head><meta name="viewport" content="width=device-width, initial-scale=1">'
              '</head><body>x</body></html>')
    assert not _fired(r, "1.4.4")


def test_1_4_10_flags_missing_viewport_when_head_has_other_content():
    r = _scan('<html><head><meta charset="utf-8"></head><body>x</body></html>')
    assert _fired(r, "1.4.10")


def test_1_4_11_flags_light_inline_border_color():
    r = _scan('<html><body><div style="border:1px solid #dddddd">box</div></body></html>')
    assert _fired(r, "1.4.11")


def test_1_4_11_ignores_dark_border():
    r = _scan('<html><body><div style="border:1px solid #333333">box</div></body></html>')
    assert not _fired(r, "1.4.11")


def test_1_4_12_flags_fixed_pixel_line_height():
    r = _scan('<html><body><p style="line-height:12px">tight</p></body></html>')
    assert _fired(r, "1.4.12")


def test_1_4_12_ignores_unitless_line_height():
    r = _scan('<html><body><p style="line-height:1.5">ok</p></body></html>')
    assert not _fired(r, "1.4.12")


def test_2_4_3_flags_positive_tabindex():
    r = _scan('<html><body><button tabindex="4">go</button></body></html>')
    assert _fired(r, "2.4.3")


def test_2_4_3_ignores_zero_or_no_tabindex():
    r = _scan('<html><body><button tabindex="0">go</button><button>ok</button></body></html>')
    assert not _fired(r, "2.4.3")


def test_2_4_7_flags_suppressed_outline_with_interactive_content():
    r = _scan("<html><head><style>a:focus{outline:none}</style></head>"
              '<body><a href="/x">go</a></body></html>')
    assert _fired(r, "2.4.7")


def test_2_4_7_ignores_suppressed_outline_with_no_interactive_content():
    r = _scan("<html><head><style>div{outline:none}</style></head><body><p>text</p></body></html>")
    assert not _fired(r, "2.4.7")


def test_3_1_4_flags_known_abbreviation():
    r = _scan("<html><body><p>See the WCAG guide for details.</p></body></html>")
    assert _fired(r, "3.1.4")


def test_3_1_4_ignores_abbreviation_already_wrapped_in_abbr():
    r = _scan('<html><body><p><abbr title="Web Content Accessibility Guidelines">WCAG</abbr> guide.</p></body></html>')
    assert not _fired(r, "3.1.4")


def test_3_1_4_ignores_prose_with_no_known_abbreviation():
    r = _scan("<html><body><p>This is a perfectly normal sentence.</p></body></html>")
    assert not _fired(r, "3.1.4")
