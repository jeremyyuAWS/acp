"""Decorative inference reads the image's SIZE, not just the shape's name.

`infer_decorative` has always accepted width/height and has three size signals — hairline,
extreme aspect ratio, icon-sized — but `remediate_office` only ever passed `filename=`, so all
three were dead code. That mattered: real documents name their images "Picture 3", which is
exactly the case the name signal cannot see. A 1x1 spacer stretched across a page was handed to
the vision model to describe, or deferred to a human, instead of being proposed as decorative.

The restraint that makes this safe: SIZE is consulted ONLY where no faithful alt source exists.
A title, a caption, or a descriptive shape name is human-authored and outranks a heuristic — a
wide banner photo named "Team Photo" has a divider's aspect ratio and is not decorative. The
error we refuse to make is proposing that real content be erased from assistive tech.
"""
import io
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))

import remediate_office  # noqa: E402

_W = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
      'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
      'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
      'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"')
_RELS = ('<?xml version="1.0"?>'
         '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
         '<Relationship Id="rId9" '
         'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" '
         'Target="media/image1.png"/></Relationships>')


def _img(w, h, fmt="PNG") -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("P" if fmt == "GIF" else "RGB", (w, h)).save(buf, format=fmt)
    return buf.getvalue()


def _photo(w, h) -> bytes:
    """A high-variance image — a real photo/chart, not a solid fill. `Image.new` yields a
    flat black rectangle, which the content signal (correctly) reads as decorative; a genuine
    'real photo' fixture must actually carry pixel variance."""
    from PIL import Image
    im = Image.new("RGB", (w, h))
    px = im.load()
    for y in range(h):                     # a full-range gradient — variance survives downscaling,
        for x in range(w):                 # unlike high-frequency noise which the box filter averages
            px[x, y] = (int(255 * x / w), int(255 * y / h), int(255 * (x + y) / (w + h)))
    buf = io.BytesIO(); im.save(buf, format="PNG"); return buf.getvalue()


def _drawing(name: str) -> str:
    n = f' name="{name}"' if name else ""
    return (f'<w:p><w:r><w:drawing><wp:docPr id="1"{n}/>'
            '<a:blip r:embed="rId9"/></w:drawing></w:r></w:p>')


def _run(tmp_path, name: str, img: bytes):
    src = tmp_path / "d.docx"
    with zipfile.ZipFile(src, "w") as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types/>')
        z.writestr("docProps/core.xml", '<?xml version="1.0"?><cp:coreProperties xmlns:cp="x"/>')
        z.writestr("word/document.xml",
                   f'<?xml version="1.0"?><w:document {_W}><w:body>{_drawing(name)}</w:body></w:document>')
        z.writestr("word/_rels/document.xml.rels", _RELS)
        z.writestr("word/media/image1.png", img)
    props: list = []
    out, _, _ = remediate_office.remediate_office(src, ai_enabled=False, proposals=props)
    with zipfile.ZipFile(out) as z:
        xml = z.read("word/document.xml").decode()
    deco = [p for p in props if p.get("kind") == "decorative"]
    return deco, xml


# ── the size signals now fire, on a generically-named image ──

def test_a_one_by_one_spacer_is_proposed_decorative(tmp_path):
    deco, _ = _run(tmp_path, "Picture 3", _img(1, 1))
    assert len(deco) == 1
    assert "hairline" in deco[0]["rationale"]
    assert "1×1px" in deco[0]["rationale"]


def test_a_hairline_rule_is_proposed_decorative(tmp_path):
    deco, _ = _run(tmp_path, "Picture 3", _img(600, 2))
    assert len(deco) == 1 and "hairline" in deco[0]["rationale"]


def test_an_extreme_aspect_ratio_reads_as_a_divider(tmp_path):
    deco, _ = _run(tmp_path, "Picture 3", _img(600, 50))     # ratio 12 >= 10, min axis > 4
    assert len(deco) == 1 and "aspect ratio" in deco[0]["rationale"]


def test_an_icon_sized_glyph_is_proposed_decorative(tmp_path):
    deco, _ = _run(tmp_path, "Picture 3", _img(16, 16))
    assert len(deco) == 1 and "icon-sized" in deco[0]["rationale"]


def test_a_tiny_gif_spacer_below_the_vision_byte_floor_still_reaches_the_heuristic(tmp_path):
    # THE bug this uncovered: _image_bytes_for dropped anything under _MIN_IMG_BYTES (64), a
    # floor written for the vision model. A 1x1 GIF spacer is 37 bytes — the clearest decorative
    # signal a document can carry — and the lookup was throwing it away.
    gif = _img(1, 1, fmt="GIF")
    assert len(gif) < remediate_office._MIN_IMG_BYTES, f"fixture must be tiny, got {len(gif)}B"
    deco, _ = _run(tmp_path, "Picture 3", gif)
    assert len(deco) == 1 and "hairline" in deco[0]["rationale"]


def test_the_size_proposal_carries_the_image(tmp_path):
    deco, _ = _run(tmp_path, "Picture 3", _img(16, 16))
    assert deco[0]["thumb"].startswith("data:image/png;base64,")


def test_a_size_proposal_is_never_auto_applied(tmp_path):
    deco, xml = _run(tmp_path, "Picture 3", _img(1, 1))
    assert len(deco) == 1
    assert "descr=" not in xml            # a heuristic never writes into the document


# ── what must NOT fire ──

def test_a_real_photo_with_a_generic_name_is_not_decorative(tmp_path):
    # Falls through to the vision/human path exactly as before. A genuine photo carries
    # variance; the content signal must not fire on it.
    deco, _ = _run(tmp_path, "Picture 3", _photo(800, 600))
    assert deco == []


# ── content signal: a near-solid fill (a background block) is decorative on pixels alone ──

def test_a_normal_sized_solid_fill_is_proposed_decorative_on_content(tmp_path):
    # A full-slide black/colour background block, ordinarily named — the case the name and size
    # signals both miss and a vision model can only call "black, nothing to describe".
    deco, _ = _run(tmp_path, "Picture 7", _img(900, 700))     # Image.new → solid fill, variance 0
    assert len(deco) == 1 and "near-solid fill" in deco[0]["rationale"]


def test_content_signal_never_auto_applies(tmp_path):
    deco, xml = _run(tmp_path, "Picture 7", _img(900, 700))
    assert len(deco) == 1
    assert "descr=" not in xml                                # still a human-confirmed proposal


def test_a_faithful_name_outranks_the_content_signal(tmp_path):
    # A solid fill deliberately named by an author is described, not erased.
    deco, xml = _run(tmp_path, "Brand colour band", _img(900, 700))
    assert deco == []
    assert 'descr="Brand colour band"' in xml


def test_a_faithful_shape_name_outranks_a_dividers_aspect_ratio(tmp_path):
    # "Team Photo" at 1200x100 has ratio 12. Erasing it from assistive tech is the expensive
    # error; a mediocre alt is the cheap one. The name wins, and the alt is written inline.
    deco, xml = _run(tmp_path, "Team Photo", _img(1200, 100))
    assert deco == []
    assert 'descr="Team Photo"' in xml


def test_a_faithful_name_that_is_also_tiny_is_still_not_size_judged(tmp_path):
    deco, xml = _run(tmp_path, "Signature of the CEO", _img(20, 20))
    assert deco == []
    assert 'descr="Signature of the CEO"' in xml


def test_a_decorative_NAME_still_wins_regardless_of_size(tmp_path):
    # The original signal is untouched: a big logo is still a logo.
    deco, _ = _run(tmp_path, "company logo", _img(800, 600))
    assert len(deco) == 1 and "looks decorative" in deco[0]["rationale"]


# ── the vision floor moved, it did not vanish ──

def test_the_vision_model_is_still_never_handed_a_degenerate_image(monkeypatch):
    import re
    import ai
    calls = []
    monkeypatch.setattr(ai, "vision_is_available", lambda: True)
    monkeypatch.setattr(ai, "describe_image_structured",
                        lambda b, **k: calls.append(b) or {"alt": "x", "grounded": True})

    xml = f"<w:body>{_drawing('Picture 3')}</w:body>"
    m = re.search(r"<wp:docPr\b([^>]*?)(/?)>", xml)
    tiny = _img(1, 1, fmt="GIF")
    entries = {"word/_rels/document.xml.rels": _RELS.encode(), "word/media/image1.png": tiny}

    # the lookup hands it over (the heuristic wants it)...
    assert remediate_office._image_bytes_for(xml, m, "wp:docPr", None, entries,
                                             "word/document.xml") is not None
    # ...but _vision_alt still refuses to describe it.
    got = remediate_office._vision_alt(xml, m, "wp:docPr", "", None, entries, "word/document.xml",
                                       True, "f.docx", None, None, None, [], [])
    assert got is None
    assert calls == [], "a 1x1 spacer must never reach the vision model"


# ── _img_size ──

def test_img_size_reads_intrinsic_pixels():
    assert remediate_office._img_size(_img(640, 480)) == (640, 480)
    assert remediate_office._img_size(_img(1, 1, fmt="GIF")) == (1, 1)


def test_img_size_never_raises_on_junk():
    assert remediate_office._img_size(b"not an image") is None
    assert remediate_office._img_size(b"") is None
