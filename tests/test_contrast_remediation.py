"""xlsx + html contrast remediation (1.4.3 / 1.4.6).

Self-contained: a minimal in-memory xlsx and crafted HTML, so the tests don't
depend on the .NET engine or fixture files. They verify the transforms
remediate_office / remediate clear what office_structure / the scanner flag —
which the end-to-end engine re-scan already confirmed on the real corpus.
"""
from __future__ import annotations
import sys
import tempfile
import zipfile
from pathlib import Path

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

import office_structure as osx          # noqa: E402
import remediate_office as rem          # noqa: E402
from remediate import remediate_html    # noqa: E402

# A low-contrast pair: font #777777 (luma .467) on a solid fill #808080 (luma .502)
# → luma-diff .035, below both the AA (.3) and AAA (.5) thresholds.
_STYLES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
    '<fonts count="1"><font><sz val="11"/><color rgb="FF777777"/></font></fonts>'
    '<fills count="3">'
    '<fill><patternFill patternType="none"/></fill>'
    '<fill><patternFill patternType="gray125"/></fill>'
    '<fill><patternFill patternType="solid"><fgColor rgb="FF808080"/></patternFill></fill>'
    '</fills>'
    '<cellXfs count="1"><xf fontId="0" fillId="2" xfId="0"/></cellXfs>'
    '</styleSheet>'
)
_SHEET = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
    '<sheetData><row r="1"><c r="A1" s="0" t="inlineStr">'
    '<is><t>Low contrast cell</t></is></c></row></sheetData></worksheet>'
)


def _write_xlsx(entries: dict) -> Path:
    out = Path(tempfile.mkdtemp()) / "book.xlsx"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in entries.items():
            z.writestr(name, data)
    return out


def test_xlsx_contrast_detected_then_cleared():
    entries = {
        "xl/styles.xml": _STYLES.encode(),
        "xl/worksheets/sheet1.xml": _SHEET.encode(),
    }
    # detector flags it before
    before = osx.xlsx_contrast_checks(_write_xlsx(entries))
    assert {f["ruleId"] for f in before} == {"XLSX_LOW_CONTRAST_AA", "XLSX_LOW_CONTRAST_AAA"}
    # remediate in place (mutates entries["xl/styles.xml"])
    applied = rem._remediate_xlsx_contrast(entries)
    assert applied and "1.4.3" in applied[0]
    # a new black/white font was cloned and the cell style repointed to it
    styles = entries["xl/styles.xml"].decode()
    assert 'count="2"' in styles and ('FF000000' in styles or 'FFFFFFFF' in styles)
    # detector no longer flags it
    after = osx.xlsx_contrast_checks(_write_xlsx(entries))
    assert after == []


def test_xlsx_contrast_noop_when_already_ok():
    ok_styles = _STYLES.replace("FF777777", "FF000000")  # black on grey → high contrast
    entries = {"xl/styles.xml": ok_styles.encode(), "xl/worksheets/sheet1.xml": _SHEET.encode()}
    assert rem._remediate_xlsx_contrast(entries) == []


def test_html_contrast_darkens_light_text():
    fixed, applied, _ = remediate_html('<html><body><p style="color:#cccccc">Body</p></body></html>')
    assert "color:#111111" in fixed.replace(" ", "")
    assert any("1.4.3" in a for a in applied)


def test_html_contrast_skips_dark_background():
    # light text on an explicit dark background — darkening would make it worse, so leave it
    html = '<html><body><p style="background:#111111;color:#cccccc">On dark</p></body></html>'
    fixed, applied, _ = remediate_html(html)
    assert "color:#cccccc" in fixed.replace(" ", "")
    assert not any("1.4.3" in a for a in applied)


# ── Hue-preserving contrast recolor (office_structure.min_contrast_recolor) ──────────
# The fix must reach AA WITHOUT flattening every colour to pure black/white — the brand
# survives, only its lightness moves.
import colorsys  # noqa: E402


def _hue(hex6):
    r, g, b = (int(hex6[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return colorsys.rgb_to_hls(r, g, b)[0]


def test_recolor_reaches_AA_on_light_background():
    # A light brand blue (#6FA8DC ~2.3:1 on white) must clear 4.5:1 after the fix.
    out = osx.min_contrast_recolor("6FA8DC", "FFFFFF")
    assert osx._contrast_ratio("FFFFFF", out) >= 4.5


def test_recolor_preserves_hue_not_flatten_to_black():
    # The fixed colour is still BLUE, just darker — not #000000.
    out = osx.min_contrast_recolor("6FA8DC", "FFFFFF")
    assert out != "000000"
    assert abs(_hue(out) - _hue("6FA8DC")) < 0.03    # same hue, within rounding


def test_recolor_lightens_on_dark_background():
    # A mid colour on near-black must be LIGHTENED (not darkened) and clear AA.
    out = osx.min_contrast_recolor("444444", "111111")
    assert osx._contrast_ratio("111111", out) >= 4.5
    assert osx._wcag_luminance(out) > osx._wcag_luminance("444444")


def test_recolor_leaves_a_passing_colour_untouched():
    assert osx.min_contrast_recolor("000000", "FFFFFF") == "000000"


def test_recolor_is_minimal_change_keeps_more_colour_than_pure_black():
    # The result is lighter than pure black — i.e. it stopped as soon as AA was met,
    # preserving more of the original colour than the old flatten-to-black behaviour.
    out = osx.min_contrast_recolor("6FA8DC", "FFFFFF")
    assert osx._wcag_luminance(out) > osx._wcag_luminance("000000")
