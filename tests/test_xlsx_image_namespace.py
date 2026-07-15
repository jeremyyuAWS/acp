"""xlsx image alt remediation must handle the two OOXML flavours real workbooks ship in.

Two bugs made every image in certain workbooks fall through as bare, un-drafted HITL findings —
no alt, no decorative inference, no vision draft, not even a thumbnail for the reviewer:

  1. NAMESPACE PREFIX — Excel authors `<xdr:pic>/<xdr:cNvPr>`, but many generators emit the same
     parts in the default spreadsheetDrawing namespace as `<pic>/<cNvPr>`. The remediator matched
     only the prefixed form, so default-namespace drawings were skipped entirely.
  2. ABSOLUTE PACKAGE PATH — a rels Target of `/xl/media/image1.png` (leading slash = "from the
     package root", valid OOXML) was treated as an external link and discarded, so the image bytes
     never resolved.

Either bug alone hides every image in the workbook from remediation. This pins both via a workbook
that uses BOTH flavours at once.
"""
import io
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))

import remediate_office  # noqa: E402


def _solid_png(w=400, h=300) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (18, 52, 86)).save(buf, format="PNG")   # a flat fill → decorative
    return buf.getvalue()


# Default-namespace spreadsheet drawing: <pic>/<cNvPr> (NOT xdr:-prefixed), junk descr "Picture".
_DRAWING = (
    '<?xml version="1.0"?>'
    '<wsDr xmlns="http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing" '
    'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
    '<twoCellAnchor><pic><nvPicPr><cNvPr id="1" name="Image 1" descr="Picture"/><cNvPicPr/></nvPicPr>'
    '<blipFill><a:blip r:embed="rId1"/></blipFill></pic></twoCellAnchor></wsDr>'
)
# Absolute package path (leading slash) — the form the bug discarded.
_DRAWING_RELS = (
    '<?xml version="1.0"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" '
    'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" '
    'Target="/xl/media/image1.png"/></Relationships>'
)


def _xlsx(tmp_path) -> Path:
    src = tmp_path / "book.xlsx"
    with zipfile.ZipFile(src, "w") as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types/>')
        z.writestr("xl/workbook.xml", '<?xml version="1.0"?><workbook/>')
        z.writestr("xl/drawings/drawing1.xml", _DRAWING)
        z.writestr("xl/drawings/_rels/drawing1.xml.rels", _DRAWING_RELS)
        z.writestr("xl/media/image1.png", _solid_png())
    return src


def test_default_namespace_drawing_with_absolute_rels_is_processed(tmp_path):
    # AI off: a flat-fill image whose bytes resolve → a decorative proposal. Getting a proposal at
    # all proves BOTH the default-namespace tag matched AND the absolute rels path resolved to the
    # image bytes (decorative inference reads the pixels — no bytes, no proposal).
    proposals: list = []
    remediate_office.remediate_office(_xlsx(tmp_path), ai_enabled=False, proposals=proposals)
    assert len(proposals) == 1, f"image was skipped — got {proposals}"
    assert proposals[0]["kind"] == "decorative"
    assert "near-solid fill" in proposals[0]["rationale"]


def test_media_path_resolves_absolute_package_target():
    # An absolute "/xl/media/…" target is an internal package path, not an external link.
    rels = _DRAWING_RELS.encode("utf-8")
    assert remediate_office._media_path(rels, "xl/drawings", "rId1") == "xl/media/image1.png"


def test_media_path_still_rejects_true_external_links():
    ext = _DRAWING_RELS.replace("/xl/media/image1.png", "https://example.com/logo.png").encode("utf-8")
    assert remediate_office._media_path(ext, "xl/drawings", "rId1") is None
