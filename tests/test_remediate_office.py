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
