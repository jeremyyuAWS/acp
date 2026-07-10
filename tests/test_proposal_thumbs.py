"""Every visual proposal carries the image the reviewer is being asked to judge.

Two proposals reached the HITL queue as text alone:

  * decorative inference (remediate_office) — "mark this decorative" inferred from the shape's
    NAME. Approving it hides the image from screen readers forever. The reviewer's entire job
    is to look at the picture and say whether the guess is right, and they were shown no
    picture. The bytes were in the package the whole time; only the vision path resolved them.

  * reading order (remediate_pdf) — the page render was produced, handed to the vision model,
    and thrown away. The reviewer confirmed a reading order for a page they could not see.

The office decorative path must work with VISION OFF (it needs no model), which is why the
r:embed → bytes lookup had to leave `_vision_alt`.
"""
import io
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))

import proposals as prop  # noqa: E402
import remediate_office  # noqa: E402

_W = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
      'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
      'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
      'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"')
_CORE_NO_LANG = '<?xml version="1.0"?><cp:coreProperties xmlns:cp="x"/>'
_RELS = ('<?xml version="1.0"?>'
         '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
         '<Relationship Id="rId9" '
         'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" '
         'Target="media/image1.png"/></Relationships>')

# A decorative-sounding NAME (so _derive_alt yields "the shape's descriptive name" and
# infer_decorative fires) on a drawing whose blip embeds rId9.
_DECO_DRAWING = ('<w:p><w:r><w:drawing><wp:docPr id="1" name="company logo"/>'
                 '<a:blip r:embed="rId9"/></w:drawing></w:r></w:p>')


def _png(w=200, h=120, colour=(200, 30, 30)) -> bytes:
    """A REAL png — PIL must be able to decode it or thumb_b64 returns None and the test
    would pass for the wrong reason (a fake b"\\x89PNG..." blob yields no thumbnail)."""
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (w, h), colour).save(buf, format="PNG")
    return buf.getvalue()


def _make_docx(path, body_xml, *, img: bytes | None = None, rels: bool = True):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types/>')
        z.writestr("docProps/core.xml", _CORE_NO_LANG)
        z.writestr("word/document.xml",
                   f'<?xml version="1.0"?><w:document {_W}><w:body>{body_xml}</w:body></w:document>')
        if rels:
            z.writestr("word/_rels/document.xml.rels", _RELS)
        if img is not None:
            z.writestr("word/media/image1.png", img)


def _decorative(proposals):
    return [p for p in proposals if p.get("kind") == "decorative"]


# ── proposals.thumb_b64 ───────────────────────────────────────────────────────

def test_thumb_b64_produces_a_png_data_url():
    t = prop.thumb_b64(_png())
    assert t.startswith("data:image/png;base64,")
    assert len(t) > 100


def test_thumb_b64_shrinks_to_max_edge():
    from PIL import Image
    import base64
    t = prop.thumb_b64(_png(400, 200), max_edge=96)
    raw = base64.b64decode(t.split(",", 1)[1])
    assert max(Image.open(io.BytesIO(raw)).size) == 96


def test_thumb_b64_honours_a_larger_max_edge_for_pages():
    from PIL import Image
    import base64
    t = prop.thumb_b64(_png(1000, 1300), max_edge=320)
    raw = base64.b64decode(t.split(",", 1)[1])
    assert max(Image.open(io.BytesIO(raw)).size) == 320


def test_thumb_b64_never_raises_on_junk():
    # A missing thumbnail must never fail remediation.
    assert prop.thumb_b64(b"not an image") is None
    assert prop.thumb_b64(b"") is None


# ── decorative proposal carries the image ─────────────────────────────────────

def test_decorative_proposal_carries_the_image_with_vision_OFF(tmp_path):
    # The regression: the bytes lookup used to live inside _vision_alt, behind `vision_enabled`.
    # Decorative inference needs no model, so with AI off the card rendered no picture at all.
    src = tmp_path / "d.docx"
    _make_docx(src, _DECO_DRAWING, img=_png())
    props: list = []
    remediate_office.remediate_office(src, ai_enabled=False, proposals=props)
    deco = _decorative(props)
    assert len(deco) == 1
    assert deco[0]["thumb"].startswith("data:image/png;base64,")


def test_decorative_proposal_thumb_is_the_embedded_image_not_a_placeholder(tmp_path):
    import base64
    from PIL import Image
    src = tmp_path / "d.docx"
    _make_docx(src, _DECO_DRAWING, img=_png(200, 120, colour=(7, 99, 200)))
    props: list = []
    remediate_office.remediate_office(src, ai_enabled=False, proposals=props)
    raw = base64.b64decode(_decorative(props)[0]["thumb"].split(",", 1)[1])
    im = Image.open(io.BytesIO(raw)).convert("RGB")
    # Same aspect as the source (within the rounding of an integer resize), and the source's
    # colour — this is that image, not a placeholder.
    assert im.size[0] / im.size[1] == pytest.approx(200 / 120, abs=0.02)
    assert im.getpixel((im.size[0] // 2, im.size[1] // 2)) == pytest.approx((7, 99, 200), abs=6)


def test_decorative_proposal_still_made_when_the_image_cannot_be_resolved(tmp_path):
    # No .rels → no bytes. The finding must still reach a human; it just carries less evidence.
    src = tmp_path / "d.docx"
    _make_docx(src, _DECO_DRAWING, img=None, rels=False)
    props: list = []
    remediate_office.remediate_office(src, ai_enabled=False, proposals=props)
    deco = _decorative(props)
    assert len(deco) == 1
    assert "thumb" not in deco[0]          # omitted, not an empty string the UI would render


def test_decorative_proposal_keeps_its_shape_name_locator(tmp_path):
    # The locator is the audit trail and is displayed; resolving the image must not change it.
    src = tmp_path / "d.docx"
    _make_docx(src, _DECO_DRAWING, img=_png())
    props: list = []
    remediate_office.remediate_office(src, ai_enabled=False, proposals=props)
    assert _decorative(props)[0]["locator"].endswith("#company logo")


def test_decorative_proposal_is_never_auto_applied(tmp_path):
    # Guard the honesty posture: a heuristic guess is a card, never a silent write.
    src = tmp_path / "d.docx"
    _make_docx(src, _DECO_DRAWING, img=_png())
    props, applied = [], []
    out, _, _ = remediate_office.remediate_office(
        src, ai_enabled=False, proposals=props, applied_fixes=applied)
    with zipfile.ZipFile(out) as z:
        xml = z.read("word/document.xml").decode()
    assert 'descr=' not in xml                    # nothing written into the document
    assert applied == []


# ── the shared image lookup is no longer vision-gated ─────────────────────────

def test_image_bytes_for_resolves_without_any_vision_flag():
    import re
    xml = f'<w:body>{_DECO_DRAWING}</w:body>'
    m = re.search(r"<wp:docPr\b([^>]*?)(/?)>", xml)
    img = _png()
    entries = {"word/_rels/document.xml.rels": _RELS.encode(), "word/media/image1.png": img}
    found = remediate_office._image_bytes_for(xml, m, "wp:docPr", None, entries, "word/document.xml")
    assert found is not None
    rid, data = found
    assert rid == "rId9" and data == img


def test_image_bytes_for_returns_none_without_entries():
    import re
    xml = f'<w:body>{_DECO_DRAWING}</w:body>'
    m = re.search(r"<wp:docPr\b([^>]*?)(/?)>", xml)
    assert remediate_office._image_bytes_for(xml, m, "wp:docPr", None, None, "word/document.xml") is None
    assert remediate_office._image_bytes_for(xml, m, "wp:docPr", None, {}, "") is None


# ── pdf reading-order proposal carries the rendered page ──────────────────────

def test_reading_order_proposal_carries_the_rendered_page(monkeypatch):
    import remediate_pdf

    page_png = _png(1000, 1300)
    monkeypatch.setattr(remediate_pdf, "_render_page_png", lambda *a, **k: page_png)

    import ai
    monkeypatch.setattr(ai, "vision_is_available", lambda: True)
    monkeypatch.setattr(ai, "describe_reading_order",
                        lambda *a, **k: {"order": "1. Title  2. Body", "model": "llava:7b"})

    class _Root(dict):
        pass

    class _Pdf:
        Root = _Root()          # no /StructTreeRoot → untagged

    props: list = []
    remediate_pdf._propose_reading_order(_Pdf(), "x.pdf", ai_enabled=True, scan_id=None,
                                         file="x.pdf", proposals=props)
    assert len(props) == 1
    p = props[0]
    assert p["kind"] == "reading-order"
    assert p["thumb"].startswith("data:image/png;base64,")


def test_reading_order_page_thumb_is_bigger_than_an_image_thumb(monkeypatch):
    # A whole page at 96px is an unreadable grey rectangle; the reviewer must be able to
    # read the page to confirm its reading order.
    import base64
    import remediate_pdf
    from PIL import Image

    monkeypatch.setattr(remediate_pdf, "_render_page_png", lambda *a, **k: _png(1000, 1300))
    import ai
    monkeypatch.setattr(ai, "vision_is_available", lambda: True)
    monkeypatch.setattr(ai, "describe_reading_order", lambda *a, **k: {"order": "1.", "model": "m"})

    class _Pdf:
        Root: dict = {}

    props: list = []
    remediate_pdf._propose_reading_order(_Pdf(), "x.pdf", ai_enabled=True, scan_id=None,
                                         file="x.pdf", proposals=props)
    raw = base64.b64decode(props[0]["thumb"].split(",", 1)[1])
    assert max(Image.open(io.BytesIO(raw)).size) == remediate_pdf._PAGE_THUMB_EDGE > 96


def test_reading_order_proposal_absent_when_the_page_will_not_render(monkeypatch):
    import remediate_pdf
    monkeypatch.setattr(remediate_pdf, "_render_page_png", lambda *a, **k: None)
    import ai
    monkeypatch.setattr(ai, "vision_is_available", lambda: True)

    class _Pdf:
        Root: dict = {}

    props: list = []
    remediate_pdf._propose_reading_order(_Pdf(), "x.pdf", ai_enabled=True, scan_id=None,
                                         file="x.pdf", proposals=props)
    assert props == []


# ── deferred alt: the reviewer must see the image they are asked to describe ───
# The same bug the decorative path had, one branch over. An image with no faithful alt
# source and no vision description is handed to a human — and the card showed them nothing.

# A GENERIC name (so _derive_alt finds no faithful source and infer_decorative declines),
# on a drawing whose blip embeds rId9 → this image defers to review.
_DEFER_DRAWING = ('<w:p><w:r><w:drawing><wp:docPr id="1" name="Picture 3"/>'
                  '<a:blip r:embed="rId9"/></w:drawing></w:r></w:p>')


def test_deferred_image_carries_a_thumbnail_with_vision_OFF(tmp_path):
    """The reviewer who most needs the picture is the one the vision model could not help."""
    src = tmp_path / "d.docx"
    _make_docx(src, _DEFER_DRAWING, img=_png())
    ev: list = []
    _, _, skipped = remediate_office.remediate_office(src, ai_enabled=False, evidence=ev)
    assert any("faithful alt source" in s for s in skipped)   # it really did defer
    assert len(ev) == 1
    assert ev[0]["thumb"].startswith("data:image/png;base64,")
    assert ev[0]["locator"] == "word/document.xml#rId9"


def test_deferred_evidence_thumb_is_the_embedded_image(tmp_path):
    """Not a placeholder: decode it and find the pixels that are actually in the package."""
    import base64
    from PIL import Image
    src = tmp_path / "d.docx"
    _make_docx(src, _DEFER_DRAWING, img=_png(240, 60, colour=(9, 121, 77)))
    ev: list = []
    remediate_office.remediate_office(src, ai_enabled=False, evidence=ev)
    raw = base64.b64decode(ev[0]["thumb"].split(",", 1)[1])
    im = Image.open(io.BytesIO(raw))
    assert max(im.size) == 96                       # shrunk to card size
    assert im.convert("RGB").getpixel((im.width // 2, im.height // 2)) == (9, 121, 77)


def test_no_evidence_when_the_image_has_a_faithful_alt_source(tmp_path):
    """A described image is fixed inline, never deferred — so it is not the reviewer's problem."""
    described = ('<w:p><w:r><w:drawing><wp:docPr id="1" name="Q3 revenue chart" '
                 'descr="Bar chart of Q3 revenue by region"/>'
                 '<a:blip r:embed="rId9"/></w:drawing></w:r></w:p>')
    src = tmp_path / "d.docx"
    _make_docx(src, described, img=_png())
    ev: list = []
    remediate_office.remediate_office(src, ai_enabled=False, evidence=ev)
    assert ev == []


def test_missing_image_bytes_never_break_remediation(tmp_path):
    """No .rels → no bytes → no thumbnail. The deferral still happens; nothing raises."""
    src = tmp_path / "d.docx"
    _make_docx(src, _DEFER_DRAWING, img=None, rels=False)
    ev: list = []
    _, _, skipped = remediate_office.remediate_office(src, ai_enabled=False, evidence=ev)
    assert any("faithful alt source" in s for s in skipped)
    assert ev == []


def test_evidence_is_optional_and_off_by_default(tmp_path):
    """Callers that pass no `evidence` list must behave exactly as before."""
    src = tmp_path / "d.docx"
    _make_docx(src, _DEFER_DRAWING, img=_png())
    _, _, skipped = remediate_office.remediate_office(src, ai_enabled=False)
    assert any("faithful alt source" in s for s in skipped)
