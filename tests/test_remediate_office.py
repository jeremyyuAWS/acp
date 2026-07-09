"""Tests for the Office (OOXML) deterministic remediator (ADR 0005 step 4).

Pure stdlib — builds a minimal OOXML package whose core.xml lacks dc:language,
then asserts the remediator sets the exact core property the .NET engine reads
(PackageProperties.Language / .Title) and produces a still-valid zip.
"""
import re
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))
import remediate_office  # noqa: E402

_CORE_NO_LANG = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n'
    '<cp:coreProperties '
    'xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
    'xmlns:dc="http://purl.org/dc/elements/1.1/">'
    '<dc:creator>x</dc:creator>'
    '</cp:coreProperties>'
)


def _make_docx(path: Path, core_xml: str):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types/>')
        z.writestr("docProps/core.xml", core_xml)
        z.writestr("word/document.xml", "<document/>")


def _core(path: Path):
    with zipfile.ZipFile(path) as z:
        xml = z.read("docProps/core.xml").decode("utf-8")
    lang = re.search(r"<dc:language>(.*?)</dc:language>", xml)
    title = re.search(r"<dc:title>(.*?)</dc:title>", xml)
    return (lang.group(1) if lang else None), (title.group(1) if title else None)


def test_sets_language_and_title(tmp_path):
    src = tmp_path / "HR-Policy-21.docx"
    _make_docx(src, _CORE_NO_LANG)
    assert _core(src) == (None, None)

    out, applied, skipped = remediate_office.remediate_office(src)
    assert out is not None
    lang, title = _core(out)
    assert lang == "en-US"
    assert title == "HR Policy 21"   # derived from filename, hyphens → spaces
    assert any("language" in a for a in applied)
    # output is still a valid OOXML zip with all parts preserved
    assert zipfile.is_zipfile(out)
    with zipfile.ZipFile(out) as z:
        assert z.testzip() is None
        assert set(z.namelist()) >= {"[Content_Types].xml", "docProps/core.xml", "word/document.xml"}


def test_idempotent_when_already_set(tmp_path):
    core = _CORE_NO_LANG.replace(
        "<dc:creator>x</dc:creator>",
        "<dc:creator>x</dc:creator><dc:language>fr-FR</dc:language><dc:title>Set</dc:title>")
    src = tmp_path / "doc.docx"
    _make_docx(src, core)
    out, applied, skipped = remediate_office.remediate_office(src)
    assert out is None           # nothing to do
    assert applied == []
    assert skipped               # explains why


def test_missing_core_part_defers(tmp_path):
    src = tmp_path / "weird.docx"
    with zipfile.ZipFile(src, "w") as z:
        z.writestr("word/document.xml", "<document/>")   # no docProps/core.xml
    out, applied, skipped = remediate_office.remediate_office(src)
    assert out is None and applied == [] and skipped


# ── Image alt text (WCAG 1.1.1 — DOCX/PPTX/XLSX-ALT-001) ─────────────────────

_W = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
      'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"')


def _make_docx_with_body(path, body_xml):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types/>')
        z.writestr("docProps/core.xml", _CORE_NO_LANG)
        z.writestr("word/document.xml",
                   f'<?xml version="1.0"?><w:document {_W}><w:body>{body_xml}</w:body></w:document>')


def _doc_xml(path):
    with zipfile.ZipFile(path) as z:
        return z.read("word/document.xml").decode("utf-8")


def test_alt_from_authors_title_field(tmp_path):
    src = tmp_path / "a.docx"
    _make_docx_with_body(src, '<w:p><w:r><w:drawing>'
                              '<wp:docPr id="1" name="Picture 1" title="Q3 revenue by region"/>'
                              '</w:drawing></w:r></w:p>')
    out, applied, _ = remediate_office.remediate_office(src)
    assert 'descr="Q3 revenue by region"' in _doc_xml(out)
    assert any("Alt-Text title" in a for a in applied)


def test_alt_from_adjacent_caption(tmp_path):
    src = tmp_path / "b.docx"
    _make_docx_with_body(src,
        '<w:p><w:r><w:drawing><wp:docPr id="1" name="Picture 1"/></w:drawing></w:r></w:p>'
        '<w:p><w:r><w:t>Figure 2: Enrollment flow for new hires</w:t></w:r></w:p>')
    out, applied, _ = remediate_office.remediate_office(src)
    assert 'descr="Enrollment flow for new hires"' in _doc_xml(out)
    assert any("adjacent caption" in a for a in applied)


def test_alt_from_meaningful_name_but_not_generic(tmp_path):
    src = tmp_path / "c.docx"
    _make_docx_with_body(src,
        '<w:p><w:r><w:drawing><wp:docPr id="1" name="Org chart 2026"/></w:drawing></w:r></w:p>'
        '<w:p><w:r><w:drawing><wp:docPr id="2" name="Picture 7"/></w:drawing></w:r></w:p>')
    out, applied, skipped = remediate_office.remediate_office(src)
    xml = _doc_xml(out)
    assert 'descr="Org chart 2026"' in xml
    assert xml.count("descr=") == 1                       # generic name NOT used
    assert any("1 image(s) lack a faithful alt source" in s for s in skipped)


def test_alt_skips_decorative_and_existing(tmp_path):
    src = tmp_path / "d.docx"
    _make_docx_with_body(src,
        '<w:p><w:r><w:drawing><wp:docPr id="1" name="x" title="tt">'
        '<a:extLst><adec:decorative val="1"/></a:extLst></wp:docPr></w:drawing></w:r></w:p>'
        '<w:p><w:r><w:drawing><wp:docPr id="2" title="unused" descr="already here"/></w:drawing></w:r></w:p>')
    out, applied, _ = remediate_office.remediate_office(src)
    xml = _doc_xml(out)
    assert 'descr="tt"' not in xml                        # decorative untouched
    assert xml.count('descr="already here"') == 1         # existing preserved
    assert not any("Alt text" in a for a in applied)


def test_alt_pptx_pictures_only(tmp_path):
    src = tmp_path / "e.pptx"
    slide = ('<?xml version="1.0"?><p:sld xmlns:p="x"><p:cSld>'
             '<p:sp><p:nvSpPr><p:cNvPr id="1" name="TitleBox" title="not a picture"/></p:nvSpPr></p:sp>'
             '<p:pic><p:nvPicPr><p:cNvPr id="2" name="Picture 3" title="Campus map with step-free routes"/>'
             '</p:nvPicPr></p:pic></p:cSld></p:sld>')
    with zipfile.ZipFile(src, "w") as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types/>')
        z.writestr("docProps/core.xml", _CORE_NO_LANG)
        z.writestr("ppt/slides/slide1.xml", slide)
    out, applied, _ = remediate_office.remediate_office(src)
    with zipfile.ZipFile(out) as z:
        xml = z.read("ppt/slides/slide1.xml").decode("utf-8")
    assert 'descr="Campus map with step-free routes"' in xml
    assert xml.count("descr=") == 1                       # the shape (non-pic) untouched


def test_alt_xlsx_drawing(tmp_path):
    src = tmp_path / "f.xlsx"
    drawing = ('<?xml version="1.0"?><xdr:wsDr xmlns:xdr="x">'
               '<xdr:pic><xdr:nvPicPr><xdr:cNvPr id="1" name="Budget flowchart"/></xdr:nvPicPr></xdr:pic>'
               '</xdr:wsDr>')
    with zipfile.ZipFile(src, "w") as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types/>')
        z.writestr("docProps/core.xml", _CORE_NO_LANG)
        z.writestr("xl/drawings/drawing1.xml", drawing)
    out, applied, _ = remediate_office.remediate_office(src)
    with zipfile.ZipFile(out) as z:
        xml = z.read("xl/drawings/drawing1.xml").decode("utf-8")
    assert 'descr="Budget flowchart"' in xml


def test_alt_junk_descr_treated_as_missing(tmp_path):
    src = tmp_path / "g.docx"
    _make_docx_with_body(src,
        '<w:p><w:r><w:drawing><wp:docPr id="1" name="Picture 1" descr="image.png" title="Waiting room floor plan"/></w:drawing></w:r></w:p>'
        '<w:p><w:r><w:drawing><wp:docPr id="2" name="Picture 2" descr="image2.jpeg"/></w:drawing></w:r></w:p>')
    out, applied, skipped = remediate_office.remediate_office(src)
    xml = _doc_xml(out)
    assert 'descr="Waiting room floor plan"' in xml       # junk replaced from title
    assert 'descr="image.png"' not in xml
    assert 'descr="image2.jpeg"' in xml                   # no faithful source → junk left, deferred
    assert any("1 image(s) lack a faithful alt source" in s for s in skipped)


def test_alt_pathstyle_descr_treated_as_missing(tmp_path):
    # Path-style descr ("icons/user.png") passes a naive non-empty check but is
    # meaningless to a screen reader — must be treated as missing alt (1.1.1).
    src = tmp_path / "h.docx"
    _make_docx_with_body(src,
        '<w:p><w:r><w:drawing><wp:docPr id="1" name="Picture 1" descr="icons/user.png" title="Patient intake diagram"/></w:drawing></w:r></w:p>'
        '<w:p><w:r><w:drawing><wp:docPr id="2" name="Picture 2" descr="icons/shield.png"/></w:drawing></w:r></w:p>')
    out, applied, skipped = remediate_office.remediate_office(src)
    xml = _doc_xml(out)
    assert 'descr="Patient intake diagram"' in xml        # path-style replaced from title
    assert 'descr="icons/user.png"' not in xml
    assert 'descr="icons/shield.png"' in xml               # no faithful source → left, deferred to human
    assert any("1 image(s) lack a faithful alt source" in s for s in skipped)


def test_alt_descriptive_slash_prose_preserved(tmp_path):
    # A real description that merely contains a slash must NOT be flagged.
    src = tmp_path / "i.docx"
    _make_docx_with_body(src,
        '<w:p><w:r><w:drawing><wp:docPr id="1" name="Picture 1" descr="Input/output flow of the intake system"/></w:drawing></w:r></w:p>')
    out, applied, _ = remediate_office.remediate_office(src)
    xml = _doc_xml(out)
    assert 'descr="Input/output flow of the intake system"' in xml   # preserved, not treated as junk
    assert not any("Alt text" in a for a in applied)


# ── Vision-generated alt text (llava-class model) ────────────────────────────
# The model is stubbed so these run offline; the live end-to-end (real llava →
# descr written → re-scan clears 1.1.1) is exercised separately against Ollama.

_RELS = ('<?xml version="1.0"?>'
         '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
         '<Relationship Id="rId9" '
         'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" '
         'Target="media/image1.png"/></Relationships>')
# A drawing with a generic name (no faithful source) whose blip embeds rId9.
_DRAWING = ('<w:p><w:r><w:drawing><wp:docPr id="1" name="Picture 1"/>'
            '<a:blip r:embed="rId9"/></w:drawing></w:r></w:p>')


def _make_docx_with_image(path, body_xml, img_bytes=b"\x89PNG\r\n\x1a\n" + b"x" * 200):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types/>')
        z.writestr("docProps/core.xml", _CORE_NO_LANG)
        z.writestr("word/document.xml",
                   f'<?xml version="1.0"?><w:document {_W}><w:body>{body_xml}</w:body></w:document>')
        z.writestr("word/_rels/document.xml.rels", _RELS)
        z.writestr("word/media/image1.png", img_bytes)


def _stub_vision(monkeypatch, alt="A red barn in a green field under a blue sky", available=True):
    import ai
    calls = {"n": 0, "bytes": None}

    def fake_describe(image_bytes, **kw):
        calls["n"] += 1
        calls["bytes"] = image_bytes
        return {"alt": alt, "model": "llava:7b"} if alt else None

    monkeypatch.setattr(ai, "vision_is_available", lambda: available)
    monkeypatch.setattr(ai, "describe_image", fake_describe)
    return calls


def test_alt_vision_fills_when_no_faithful_source(tmp_path, monkeypatch):
    calls = _stub_vision(monkeypatch)
    src = tmp_path / "v.docx"
    _make_docx_with_image(src, _DRAWING, img_bytes=b"\x89PNG\r\n\x1a\n" + b"real-image" * 30)
    out, applied, skipped = remediate_office.remediate_office(src, ai_enabled=True)
    xml = _doc_xml(out)
    assert 'descr="A red barn in a green field under a blue sky"' in xml
    assert any("AI vision description" in a for a in applied)
    assert not any("faithful alt source" in s for s in skipped)   # vision closed it, not deferred
    assert calls["n"] == 1
    assert calls["bytes"].startswith(b"\x89PNG")                  # got the real image bytes


def test_alt_faithful_source_wins_over_vision(tmp_path, monkeypatch):
    calls = _stub_vision(monkeypatch)
    src = tmp_path / "w.docx"
    _make_docx_with_image(src,
        '<w:p><w:r><w:drawing><wp:docPr id="1" name="Picture 1" title="Author supplied alt"/>'
        '<a:blip r:embed="rId9"/></w:drawing></w:r></w:p>')
    out, applied, _ = remediate_office.remediate_office(src, ai_enabled=True)
    assert 'descr="Author supplied alt"' in _doc_xml(out)
    assert calls["n"] == 0                                        # vision never called


def test_alt_vision_not_called_when_ai_off(tmp_path, monkeypatch):
    calls = _stub_vision(monkeypatch)
    src = tmp_path / "x.docx"
    _make_docx_with_image(src, _DRAWING)
    out, applied, skipped = remediate_office.remediate_office(src, ai_enabled=False)
    assert calls["n"] == 0                                        # AI-off: no model call
    assert not any("AI vision" in a for a in applied)
    assert any("faithful alt source" in s for s in skipped)      # deferred to human review


def test_alt_defers_when_vision_unavailable(tmp_path, monkeypatch):
    # AI on but the vision model isn't pulled → degrade to deferral, never junk.
    calls = _stub_vision(monkeypatch, available=False)
    src = tmp_path / "y.docx"
    _make_docx_with_image(src, _DRAWING)
    out, applied, skipped = remediate_office.remediate_office(src, ai_enabled=True)
    assert calls["n"] == 0
    assert any("faithful alt source" in s for s in skipped)


def test_alt_vision_miss_defers(tmp_path, monkeypatch):
    # Vision reachable but returns nothing usable → defer (don't write junk/empty).
    calls = _stub_vision(monkeypatch, alt=None)
    src = tmp_path / "z.docx"
    _make_docx_with_image(src, _DRAWING)
    out, applied, skipped = remediate_office.remediate_office(src, ai_enabled=True)
    assert calls["n"] == 1
    assert not any("AI vision" in a for a in applied)
    assert any("faithful alt source" in s for s in skipped)


# ── applied_fixes sink: the real value written + an image thumbnail (Recent AI fixes) ──

def test_applied_fixes_capture_value_and_thumbnail(tmp_path, monkeypatch):
    import io as _io
    from PIL import Image
    buf = _io.BytesIO(); Image.new("RGB", (120, 80), (200, 30, 30)).save(buf, format="PNG")
    _stub_vision(monkeypatch, alt="A red rectangle on a white background")
    src = tmp_path / "cap.docx"
    _make_docx_with_image(src, _DRAWING, img_bytes=buf.getvalue())
    sink = []
    out, applied, _ = remediate_office.remediate_office(src, ai_enabled=True, applied_fixes=sink)
    assert 'descr="A red rectangle on a white background"' in _doc_xml(out)
    assert len(sink) == 1
    rec = sink[0]
    assert rec["rule_id"] == "SC_1_1_1"
    assert rec["value"] == "A red rectangle on a white background"
    assert rec["thumb"] and rec["thumb"].startswith("data:image/png;base64,")   # decodable → real thumb


def test_applied_fixes_thumbnail_none_on_undecodable_image(tmp_path, monkeypatch):
    # A non-image blob still captures the alt text but yields a None thumbnail — never raises.
    _stub_vision(monkeypatch, alt="Some description")
    src = tmp_path / "cap2.docx"
    _make_docx_with_image(src, _DRAWING, img_bytes=b"\x89PNG\r\n\x1a\n" + b"notreal" * 20)
    sink = []
    remediate_office.remediate_office(src, ai_enabled=True, applied_fixes=sink)
    assert len(sink) == 1 and sink[0]["value"] == "Some description"
    assert sink[0]["thumb"] is None


def test_applied_fixes_sink_empty_without_vision(tmp_path, monkeypatch):
    # AI-off: faithful-only, nothing vision-generated → no applied_fixes captured.
    _stub_vision(monkeypatch)
    src = tmp_path / "cap3.docx"
    _make_docx_with_image(src, _DRAWING)
    sink = []
    remediate_office.remediate_office(src, ai_enabled=False, applied_fixes=sink)
    assert sink == []
