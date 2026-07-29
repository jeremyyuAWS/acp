"""1.1.1 on docx/pptx/xlsx: first-party detectors, so the Office credit gate is real evidence.

`RULE_FORMATS` has always listed all three formats for 1.1.1, but the only implementations were
the partner catalog's DOCX-ALT-001 / PPTX-ALT-001 / XLSX-ALT-001. The in-process re-scan that
grants credit — `proposals.verify_residual_scs`, which runs first-party checks only — therefore
could not observe 1.1.1 on an Office file at all. So `handlers._apply_one_value_kind` wrote the
reviewer's approved alt text, asked "is 1.1.1 still failing?", got back a residual set that
structurally could never contain it, and credited the criterion on no evidence.

Demonstrated before this landed: demo-fixtures/powerpoint-accessibility-demo.pptx carries six
shapes with no `descr`, and a residual re-scan of it reported no 1.1.1.

These pin the detectors, their agreement with the APPLIER (a locator the detector reports must
be one apply_alt can resolve, or the criterion can never clear), and the gate end to end with
the real re-scan on the real demo fixtures.
"""
from __future__ import annotations
import io
import sys
import zipfile
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

from apply_alt import apply_alt_text  # noqa: E402
from formats.office import images  # noqa: E402
from office_structure import checks_for  # noqa: E402
from proposals import verify_residual_scs  # noqa: E402

DEMOS = ACP / "demo-fixtures"

# part name, alt-bearing tag, optional picture wrapper — one per format.
SHAPES = {
    "docx": ("word/document.xml", "wp:docPr", None),
    "pptx": ("ppt/slides/slide1.xml", "p:cNvPr", "p:pic"),
    "xlsx": ("xl/drawings/drawing1.xml", "xdr:cNvPr", "xdr:pic"),
}


def _pkg(fmt: str, inner: str) -> bytes:
    part, _, _ = SHAPES[fmt]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(part, f"<root>{inner}</root>")
        z.writestr("docProps/core.xml", "<cp:coreProperties/>")
    return buf.getvalue()


def _shape(fmt: str, name: str, *, descr: str | None = None, decorative: bool = False,
           wrap: bool = True) -> str:
    _, tag, wrapper = SHAPES[fmt]
    attrs = f' name="{name}"' + (f' descr="{descr}"' if descr is not None else "")
    body = f'<a:extLst><a16:decorative val="1"/></a:extLst>' if decorative else ""
    el = f"<{tag}{attrs}>{body}</{tag}>"
    if wrapper and wrap:
        el = f"<{wrapper}>{el}</{wrapper}>"
    return el


def _detect(fmt: str, data: bytes, tmp_path: Path) -> list[dict]:
    p = tmp_path / f"f.{fmt}"
    p.write_bytes(data)
    return [i for i in checks_for(p, p.suffix) if i["wcag"].startswith("1.1.1")]


# ── the detectors ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("fmt", ["docx", "pptx", "xlsx"])
def test_an_image_with_no_alt_is_reported(fmt, tmp_path):
    found = _detect(fmt, _pkg(fmt, _shape(fmt, "Picture 1")), tmp_path)
    assert len(found) == 1
    assert found[0]["ruleId"] == f"{fmt.upper()}_IMAGE_NO_ALT"
    assert found[0]["locator"] == f"{SHAPES[fmt][0]}#Picture 1"


@pytest.mark.parametrize("fmt", ["docx", "pptx", "xlsx"])
def test_a_described_image_is_not_reported(fmt, tmp_path):
    data = _pkg(fmt, _shape(fmt, "Picture 1", descr="A bar chart of revenue by region"))
    assert _detect(fmt, data, tmp_path) == []


@pytest.mark.parametrize("fmt", ["docx", "pptx", "xlsx"])
def test_a_decorative_image_is_conforming_and_not_reported(fmt, tmp_path):
    """WCAG 1.1.1 permits a decorative image to carry no alt. Flagging one would be a false
    positive AND unclearabe — the remediator skips it, so the criterion could never clear."""
    data = _pkg(fmt, _shape(fmt, "Divider", decorative=True))
    assert _detect(fmt, data, tmp_path) == []


@pytest.mark.parametrize("junk", ["", "Picture 1", "image3.png", "media/image1.png", "   "])
def test_a_junk_description_counts_as_undescribed(junk, tmp_path):
    """An auto-name or a filename is meaningless to a screen reader, so it is not alt text."""
    data = _pkg("pptx", _shape("pptx", "Chart 2", descr=junk))
    assert len(_detect("pptx", data, tmp_path)) == 1


def test_a_shape_outside_a_picture_wrapper_is_not_an_image(tmp_path):
    """pptx/xlsx put cNvPr on EVERY shape; only pictures need alt. A text box is not an image."""
    data = _pkg("pptx", _shape("pptx", "TextBox 1", wrap=False))
    assert _detect("pptx", data, tmp_path) == []


def test_an_unnamed_element_is_skipped(tmp_path):
    """No name means no addressable locator, so an approval could never be written back."""
    data = _pkg("pptx", "<p:pic><p:cNvPr/></p:pic>")
    assert _detect("pptx", data, tmp_path) == []


def test_a_file_that_is_not_a_package_is_survived(tmp_path):
    p = tmp_path / "junk.docx"
    p.write_bytes(b"not a zip")
    assert _detect("docx", b"not a zip", tmp_path) == []


# ── detector / applier agreement ──────────────────────────────────────────────

def test_default_namespace_xlsx_drawings_are_resolvable_by_the_applier(tmp_path):
    """THE regression in apply_alt: its part→tag table was a hand-copy of the remediator's, and
    when that gained `(?:xdr:)?` for default-namespace drawings this copy kept `xdr:cNvPr`. The
    table that minted a locator could no longer resolve it, so every approval on such a workbook
    came back unresolved and was silently never written."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:                     # default namespace: <pic>/<cNvPr>
        z.writestr("xl/drawings/drawing1.xml",
                   '<root><pic><cNvPr name="Image 1"/></pic></root>')
    data = buf.getvalue()
    found = _detect("xlsx", data, tmp_path)
    assert len(found) == 1, "the detector missed a default-namespace drawing"

    fixed, applied, unresolved = apply_alt_text(data, {found[0]["locator"]: "A revenue chart"})
    assert unresolved == [], "the applier could not resolve the locator the detector minted"
    assert len(applied) == 1
    xml = zipfile.ZipFile(io.BytesIO(fixed)).read("xl/drawings/drawing1.xml").decode()
    assert 'descr="A revenue chart"' in xml
    assert "<cNvPr" in xml and "xdr:cNvPr" not in xml, "the document's own spelling was rewritten"


@pytest.mark.parametrize("demo", ["word-accessibility-demo.docx",
                                  "powerpoint-accessibility-demo.pptx",
                                  "excel-accessibility-demo.xlsx"])
def test_every_reported_locator_is_one_the_applier_can_write(demo):
    """If the detector reports an image the applier cannot address, the criterion never clears
    and the file can never certify — the approval is written and then refused credit, forever."""
    p = DEMOS / demo
    found = [i for i in checks_for(p, p.suffix) if i["wcag"].startswith("1.1.1")]
    assert found, f"{demo} is expected to carry undescribed images"
    _fixed, applied, unresolved = apply_alt_text(
        p.read_bytes(), {i["locator"]: "A described image" for i in found})
    assert unresolved == []
    assert len(applied) == len(found)


# ── the gate, end to end, on the real fixtures ────────────────────────────────

@pytest.mark.parametrize("demo", ["word-accessibility-demo.docx",
                                  "powerpoint-accessibility-demo.pptx",
                                  "excel-accessibility-demo.xlsx"])
def test_the_credit_gate_now_rests_on_a_rescan_that_can_see_1_1_1(demo):
    """THE point of this change: 1.1.1 is observable before the write and gone after it.

    Before these detectors this criterion was absent from the residual set in BOTH states, so
    the gate cleared it without anything having been described.
    """
    p = DEMOS / demo
    assert "1.1.1" in (verify_residual_scs(p.read_bytes(), p.name) or set()), (
        f"the re-scan cannot see 1.1.1 on {demo} — the gate would be vacuous again")
    found = [i for i in checks_for(p, p.suffix) if i["wcag"].startswith("1.1.1")]
    fixed, _applied, _unresolved = apply_alt_text(
        p.read_bytes(), {i["locator"]: "A described image" for i in found})
    assert "1.1.1" not in (verify_residual_scs(fixed, p.name) or set())


def test_describing_only_some_images_leaves_the_criterion_failing():
    """The gate's teeth: a partial write must NOT clear 1.1.1, or the file certifies with an
    undescribed image still in it."""
    p = DEMOS / "powerpoint-accessibility-demo.pptx"
    found = [i for i in checks_for(p, p.suffix) if i["wcag"].startswith("1.1.1")]
    assert len(found) > 1, "fixture needs at least two undescribed images"
    fixed, _a, _u = apply_alt_text(p.read_bytes(), {found[0]["locator"]: "A described image"})
    assert "1.1.1" in (verify_residual_scs(fixed, p.name) or set())


# ── remediator agreement ──────────────────────────────────────────────────────

def test_the_remediator_shares_this_predicate(tmp_path):
    """remediate_office must judge 'described' identically, or the two drift into either an
    uncertifiable file or a certified one with undescribed images."""
    import remediate_office as RO
    assert RO._ALT_TARGETS is images.ALT_TARGETS
    for value in ("", "Picture 1", "image3.png", "media/image1.png"):
        assert RO._is_junk_descr(value) is images.is_junk_descr(value) is True
    assert RO._is_junk_descr("A bar chart of revenue") is False
