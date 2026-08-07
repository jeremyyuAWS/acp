"""Review cards for 1.4.1 / 1.4.11 must carry their measurement, not only describe it.

These two criteria are REVIEW-LANE ONLY on Office formats (`RULE_FORMATS` scopes both to
html; `REVIEW_FORMATS` is what puts them on docx/xlsx/pptx/pdf). So no remediation lane is
possible for them by construction -- the contract in remediation_capability keys on
RULE_FORMATS -- and the honest ceiling is a guided card. What makes that card useful is the
number: a reviewer told "a shape outline is too faint" has to go and measure it, while one
told "1.42:1, needs 3:1" can act.

The detectors already HELD the number and spent it on prose. pdf and pptx passed it as
structured `evidence` (ADR 0026); docx and xlsx computed the identical ratio and dropped it.
Asserted per format rather than in one place because that asymmetry is exactly the kind that
returns -- the four 1.4.11 detectors are near-copies of each other, so a fifth will be too.
"""
from __future__ import annotations
import io
import sys
import zipfile
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

import office_structure as osx  # noqa: E402

# A solid outline on a solid fill, close enough in luminance to fall under 3:1.
_SHAPE = ('<wps:spPr xmlns:wps="x" xmlns:a="y">'
          '<a:solidFill><a:srgbClr val="8A8A8A"/></a:solidFill>'
          '<a:ln><a:solidFill><a:srgbClr val="9A9A9A"/></a:solidFill></a:ln>'
          '</wps:spPr>')


def _zip(parts: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for n, body in parts.items():
            z.writestr(n, body)
    return buf.getvalue()


def _only(findings: list[dict]) -> dict:
    assert len(findings) == 1, f"expected exactly one finding, got {findings}"
    return findings[0]


# ── 1.4.11 Non-text Contrast — the measured ratio ────────────────────────────

def test_docx_nontext_contrast_carries_the_measured_ratio(tmp_path):
    p = tmp_path / "f.docx"
    p.write_bytes(_zip({"word/document.xml": f"<w:document>{_SHAPE}</w:document>"}))
    ev = _only(osx.docx_nontext_contrast_checks(p)).get("evidence")
    assert ev, "the ratio is computed and stated in prose but never carried"
    assert ev["metric"] == "Contrast" and ev["required"] == 3.0 and ev["unit"] == ":1"
    assert 1.0 <= ev["value"] < 3.0


def test_xlsx_nontext_contrast_carries_the_measured_ratio(tmp_path):
    p = tmp_path / "f.xlsx"
    p.write_bytes(_zip({"xl/drawings/drawing1.xml": f"<xdr:wsDr>{_SHAPE.replace('wps:', 'xdr:')}"
                                                    f"</xdr:wsDr>"}))
    ev = _only(osx.xlsx_nontext_contrast_checks(p)).get("evidence")
    assert ev and ev["metric"] == "Contrast" and ev["required"] == 3.0


def test_every_format_reports_the_ratio_the_same_way(tmp_path):
    """docx and pptx are near-copies; their cards must not disagree on shape."""
    d = tmp_path / "d.docx"
    d.write_bytes(_zip({"word/document.xml": f"<w:document>{_SHAPE}</w:document>"}))
    # pptx wants the shape-properties element inside a <p:sp> shape; docx reads <wps:spPr>
    # directly. Same DrawingML inside either way.
    pp = tmp_path / "p.pptx"
    pp.write_bytes(_zip({"ppt/slides/slide1.xml":
                         f"<p:sld><p:sp>{_SHAPE.replace('wps:', 'p:')}</p:sp></p:sld>"}))
    a = _only(osx.docx_nontext_contrast_checks(d))["evidence"]
    b = _only(osx.pptx_nontext_contrast_checks(pp))["evidence"]
    assert a.keys() == b.keys()
    assert (a["metric"], a["required"], a["unit"]) == (b["metric"], b["required"], b["unit"])


# ── 1.4.1 Use of Color — how much there is to check ──────────────────────────

def test_docx_colour_only_links_carry_their_count(tmp_path):
    link = ('<w:hyperlink r:id="rId1"><w:r><w:rPr><w:u w:val="none"/></w:rPr>'
            '<w:t>terms</w:t></w:r></w:hyperlink>')
    p = tmp_path / "f.docx"
    p.write_bytes(_zip({"word/document.xml": f"<w:document>{link}{link}</w:document>"}))
    ev = _only(osx.office_color_only_checks(p, ".docx")).get("evidence")
    assert ev and ev["metric"] == "Colour-only links" and ev["value"] == 2
    # A count with no threshold: one colour-only link is already the barrier, so there is no
    # "required" to compare against and inventing one would be a synthesized number (ADR 0016).
    assert "required" not in ev


def test_xlsx_colour_only_rules_carry_their_count(tmp_path):
    sheet = ('<worksheet><cfRule type="colorScale"/>'
             '<cfRule type="cellIs" dxfId="0"/></worksheet>')
    p = tmp_path / "f.xlsx"
    p.write_bytes(_zip({"xl/worksheets/sheet1.xml": sheet}))
    ev = _only(osx.office_color_only_checks(p, ".xlsx")).get("evidence")
    assert ev and ev["metric"] == "Colour-only rules" and ev["value"] == 2


def test_a_clean_document_still_produces_no_card(tmp_path):
    """Evidence must not turn an advisory detector into one that always fires."""
    p = tmp_path / "f.docx"
    p.write_bytes(_zip({"word/document.xml": "<w:document><w:p/></w:document>"}))
    assert osx.docx_nontext_contrast_checks(p) == []
    assert osx.office_color_only_checks(p, ".docx") == []


def test_the_cards_stay_advisory_and_unblocking(tmp_path):
    """REVIEW severity carries zero penalty weight; adding evidence must not change that."""
    p = tmp_path / "f.docx"
    p.write_bytes(_zip({"word/document.xml": f"<w:document>{_SHAPE}</w:document>"}))
    f = _only(osx.docx_nontext_contrast_checks(p))
    assert f["severity"] == "REVIEW" and f["advisory"] is True
