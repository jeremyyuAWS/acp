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
