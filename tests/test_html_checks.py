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


def _skips(result):
    return [i for i in result["issues"] if i["ruleId"] == "HTML_HEADING_SKIP"]


def test_2_4_6_every_heading_skip_reported_not_just_the_first():
    """The detector used to `break` after the first gap, so a page with several reported one —
    understating the work and reading as one edit from clean when it was several. The remediator
    (_fix_heading_skip) has always closed every gap in a single pass, so the report now matches
    it. Mirror of test_office_structure's docx case."""
    r = _scan("<html><body><h1>One</h1><h3>Three</h3><h1>Two</h1><h4>Four</h4></body></html>")
    skips = _skips(r)
    assert len(skips) == 2, [i.get("detail") for i in skips]
    details = " | ".join(i["detail"] for i in skips)
    assert "h1 to h3" in details and "h1 to h4" in details
    # Each finding names the offending heading's position, so two identical gaps stay distinct.
    assert len({i["detail"] for i in skips}) == 2


def test_2_4_6_single_gap_not_double_reported_when_outline_resumes():
    """h1→h3→h4 is ONE gap: the h3→h4 step is well-formed. `prev_level` must advance to the level
    actually in the document, not the clamped prev+1, or the rest of the outline cascades."""
    r = _scan("<html><body><h1>One</h1><h3>Three</h3><h4>Four</h4></body></html>")
    assert len(_skips(r)) == 1, [i.get("detail") for i in _skips(r)]


def test_2_4_6_sequential_headings_not_flagged():
    r = _scan("<html><body><h1>One</h1><h2>Two</h2><h3>Three</h3></body></html>")
    assert not _fired(r, "2.4.6")


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
