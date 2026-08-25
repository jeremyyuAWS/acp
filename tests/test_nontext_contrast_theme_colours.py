"""1.4.11 non-text contrast — theme-colour resolution for docx and pptx shapes.

Before this fix, shapes whose outline or fill used a DrawingML <a:schemeClr> (theme
colour reference) were silently skipped — the detector only matched explicit
<a:srgbClr val="RRGGBB">.  The new _resolve_solidfill() helper resolves schemeClr
through the file's theme XML, applies any lumMod/lumOff modifiers, and falls back to
the explicit path when no theme is present.
"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

import office_structure as osx  # noqa: E402

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
WPS = "http://schemas.microsoft.com/office/word/2010/wordprocessingShape"

# ── Minimal theme XML ─────────────────────────────────────────────────────────

_THEME_LIGHT_ON_LIGHT = """\
<a:theme xmlns:a="{A}">
  <a:themeElements>
    <a:clrScheme name="Test">
      <a:dk1><a:sysClr val="windowText" lastClr="000000"/></a:dk1>
      <a:lt1><a:sysClr val="window" lastClr="FFFFFF"/></a:lt1>
      <a:dk2><a:srgbClr val="44546A"/></a:dk2>
      <a:lt2><a:srgbClr val="E7E6E6"/></a:lt2>
      <a:accent1><a:srgbClr val="C8C8C8"/></a:accent1>
      <a:accent2><a:srgbClr val="000000"/></a:accent2>
    </a:clrScheme>
  </a:themeElements>
</a:theme>
""".format(A=A)
# accent1 = #C8C8C8, lt1 = #FFFFFF → contrast ~1.6:1 (below 3:1 → FAINT)
# accent2 = #000000, lt1 = #FFFFFF → contrast 21:1 (above 3:1 → STRONG)


def _scheme_shape(border_scheme: str, fill_scheme: str, *, lum_mod: int | None = None,
                  lum_off: int | None = None) -> str:
    """A wps:spPr shape using schemeClr references for both outline and fill."""
    def _modifiers(lm: int | None, lo: int | None) -> str:
        parts = ""
        if lm is not None:
            parts += f'<a:lumMod val="{lm}"/>'
        if lo is not None:
            parts += f'<a:lumOff val="{lo}"/>'
        return parts

    return (
        f'<wps:wsp xmlns:wps="{WPS}" xmlns:a="{A}"><wps:spPr>'
        f'<a:ln><a:solidFill><a:schemeClr val="{border_scheme}">'
        f'{_modifiers(lum_mod, lum_off)}</a:schemeClr></a:solidFill></a:ln>'
        f'<a:solidFill><a:schemeClr val="{fill_scheme}"/></a:solidFill>'
        f'</wps:spPr></wps:wsp>'
    )


def _pptx_scheme_shape(border_scheme: str, fill_scheme: str, *, lum_mod: int | None = None,
                       lum_off: int | None = None) -> str:
    """A p:sp using schemeClr references for both outline and fill.

    Namespaces declared on the wrapping slide element, not here — matches what
    _PPTX_SP expects: <p:sp> without attributes."""
    def _modifiers(lm: int | None, lo: int | None) -> str:
        parts = ""
        if lm is not None:
            parts += f'<a:lumMod val="{lm}"/>'
        if lo is not None:
            parts += f'<a:lumOff val="{lo}"/>'
        return parts

    return (
        f'<p:sp><p:spPr>'
        f'<a:ln><a:solidFill><a:schemeClr val="{border_scheme}">'
        f'{_modifiers(lum_mod, lum_off)}</a:schemeClr></a:solidFill></a:ln>'
        f'<a:solidFill><a:schemeClr val="{fill_scheme}"/></a:solidFill>'
        f'</p:spPr></p:sp>'
    )


# ── docx fixtures ─────────────────────────────────────────────────────────────

def _build_docx(path: Path, shape_xml: str, *, theme_xml: str = _THEME_LIGHT_ON_LIGHT) -> Path:
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml",
                   f'<w:document xmlns:w="{W}"><w:body><w:p>{shape_xml}</w:p></w:body></w:document>')
        z.writestr("word/theme/theme1.xml", theme_xml)
    return path


def _fires_docx(path: Path) -> bool:
    return any(f.get("ruleId") == "DOCX_NONTEXT_LOW_CONTRAST"
               for f in osx.docx_nontext_contrast_checks(path))


# ── pptx fixtures ─────────────────────────────────────────────────────────────

def _build_pptx(path: Path, shape_xml: str, *, theme_xml: str = _THEME_LIGHT_ON_LIGHT) -> Path:
    P = "http://schemas.openxmlformats.org/presentationml/2006/main"
    slide = f'<p:sld xmlns:p="{P}" xmlns:a="{A}"><p:cSld><p:spTree>{shape_xml}</p:spTree></p:cSld></p:sld>'
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("ppt/slides/slide1.xml", slide)
        z.writestr("ppt/theme/theme1.xml", theme_xml)
    return path


def _fires_pptx(path: Path) -> bool:
    return any(f.get("ruleId") == "PPTX_NONTEXT_LOW_CONTRAST"
               for f in osx.pptx_nontext_contrast_checks(path))


# ── helpers ───────────────────────────────────────────────────────────────────

def test_parse_ooxml_theme_clrs_extracts_srgb():
    clrs = osx._parse_ooxml_theme_clrs(_THEME_LIGHT_ON_LIGHT)
    assert clrs["accent1"] == "C8C8C8"
    assert clrs["accent2"] == "000000"
    assert clrs["lt1"] == "FFFFFF"


def test_parse_ooxml_theme_clrs_extracts_sysclr():
    clrs = osx._parse_ooxml_theme_clrs(_THEME_LIGHT_ON_LIGHT)
    assert clrs["dk1"] == "000000"


def test_resolve_solidfill_falls_back_to_srgb_when_no_theme():
    xml = '<a:solidFill><a:srgbClr val="AABBCC"/></a:solidFill>'
    assert osx._resolve_solidfill(xml, None) == "AABBCC"


def test_resolve_solidfill_scheme_clr_resolved_via_theme():
    xml = '<a:solidFill><a:schemeClr val="accent1"/></a:solidFill>'
    clrs = {"accent1": "C8C8C8"}
    assert osx._resolve_solidfill(xml, clrs) == "C8C8C8"


def test_resolve_solidfill_scheme_clr_with_lum_mod():
    """lumMod=50000 halves the luminance — dark grey becomes darker."""
    xml = '<a:solidFill><a:schemeClr val="lt1"><a:lumMod val="50000"/></a:schemeClr></a:solidFill>'
    clrs = {"lt1": "FFFFFF"}   # full white
    result = osx._resolve_solidfill(xml, clrs)
    assert result is not None
    assert result != "FFFFFF"  # should have darkened
    # 50% luminance of white in HLS: L=1.0 * 0.5 = 0.5 → #808080-ish
    assert result.upper()[:2] == "80" or int(result[:2], 16) in range(0x78, 0x88)


def test_resolve_solidfill_scheme_clr_unresolvable_returns_none():
    xml = '<a:solidFill><a:schemeClr val="accent99"/></a:solidFill>'
    clrs = {"accent1": "C8C8C8"}
    assert osx._resolve_solidfill(xml, clrs) is None


def test_apply_lum_mod_off_pure_scale():
    """100% white scaled to 50% luminance → ~50% grey."""
    result = osx._apply_lum_mod_off("FFFFFF", 50000, 0)
    r = int(result[:2], 16)
    assert 0x78 <= r <= 0x88, f"expected ~0x80, got {result}"


def test_apply_lum_mod_off_offset_lifts_dark():
    """50% grey pushed up by 25% offset."""
    result = osx._apply_lum_mod_off("808080", 100000, 25000)
    r = int(result[:2], 16)
    assert r > 0x80, f"should be lighter than 0x80, got {result}"


# ── docx integration ──────────────────────────────────────────────────────────

def test_docx_theme_colour_faint_shape_fires(tmp_path):
    """A docx shape using schemeClr accent1 (#C8C8C8) on lt1 (#FFFFFF) resolves to ~1.6:1
    and must raise DOCX_NONTEXT_LOW_CONTRAST."""
    shape = _scheme_shape("accent1", "lt1")
    p = _build_docx(tmp_path / "faint.docx", shape)
    assert _fires_docx(p), "expected DOCX_NONTEXT_LOW_CONTRAST for low-contrast theme colours"


def test_docx_theme_colour_strong_shape_silent(tmp_path):
    """accent2 (#000000) on lt1 (#FFFFFF) is 21:1 — must stay silent."""
    shape = _scheme_shape("accent2", "lt1")
    p = _build_docx(tmp_path / "strong.docx", shape)
    assert not _fires_docx(p)


def test_docx_theme_colour_with_lum_mod_faint_fires(tmp_path):
    """lt1 (white) scaled to 80% luminance as border on lt1 (white) fill → very faint → fires."""
    # 80% lum of white → ~#CCCCCC; on white ~1.6:1 → below 3:1
    shape = _scheme_shape("lt1", "lt1", lum_mod=80000)
    p = _build_docx(tmp_path / "faint_mod.docx", shape)
    assert _fires_docx(p)


def test_docx_missing_theme_xml_still_matches_srgb(tmp_path):
    """Fallback: no word/theme/theme1.xml but explicit srgbClr still works."""
    border_hex, fill_hex = "C8C8C8", "FFFFFF"
    shape = (
        f'<wps:wsp xmlns:wps="{WPS}" xmlns:a="{A}"><wps:spPr>'
        f'<a:ln><a:solidFill><a:srgbClr val="{border_hex}"/></a:solidFill></a:ln>'
        f'<a:solidFill><a:srgbClr val="{fill_hex}"/></a:solidFill>'
        f'</wps:spPr></wps:wsp>'
    )
    p = tmp_path / "no_theme.docx"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("word/document.xml",
                   f'<w:document xmlns:w="{W}"><w:body><w:p>{shape}</w:p></w:body></w:document>')
    assert _fires_docx(p)


def test_docx_theme_colour_no_theme_file_scheme_clr_skipped(tmp_path):
    """Without a theme file, schemeClr shapes cannot resolve — silently skipped (no false finding)."""
    shape = _scheme_shape("accent1", "lt1")
    p = tmp_path / "no_theme_schemeonly.docx"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("word/document.xml",
                   f'<w:document xmlns:w="{W}"><w:body><w:p>{shape}</w:p></w:body></w:document>')
    # Cannot resolve → not measured → no finding
    assert not _fires_docx(p)


# ── pptx integration ──────────────────────────────────────────────────────────

def test_pptx_theme_colour_faint_shape_fires(tmp_path):
    """A pptx shape using schemeClr accent1 (#C8C8C8) on lt1 (#FFFFFF) → ~1.6:1 → fires."""
    shape = _pptx_scheme_shape("accent1", "lt1")
    p = _build_pptx(tmp_path / "faint.pptx", shape)
    assert _fires_pptx(p), "expected PPTX_NONTEXT_LOW_CONTRAST for low-contrast theme colours"


def test_pptx_theme_colour_strong_shape_silent(tmp_path):
    """accent2 (#000000) on lt1 (#FFFFFF) is 21:1 — must stay silent."""
    shape = _pptx_scheme_shape("accent2", "lt1")
    p = _build_pptx(tmp_path / "strong.pptx", shape)
    assert not _fires_pptx(p)


def test_pptx_theme_colour_with_lum_mod_faint_fires(tmp_path):
    """pptx: lt1 (white) at 80% lum as border on white fill → faint → fires."""
    shape = _pptx_scheme_shape("lt1", "lt1", lum_mod=80000)
    p = _build_pptx(tmp_path / "faint_mod.pptx", shape)
    assert _fires_pptx(p)
