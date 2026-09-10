from datetime import datetime, timezone
from io import BytesIO
from xml.etree import ElementTree as ET
from zipfile import ZipFile, ZIP_DEFLATED

import pikepdf
import pytest
from output_provenance import stamp_output, CUSTOM_NS

NOW = datetime(2026, 9, 10, 4, 5, 6, tzinfo=timezone.utc)


def test_pdf_refreshes_xmp_and_docinfo_without_changing_content(monkeypatch):
    monkeypatch.setenv("ACP_BUILD_VERSION", "2026.9.10.7")
    pdf = pikepdf.Pdf.new()
    pdf.add_blank_page()
    pdf.docinfo["/Title"] = "Original title"
    pdf.docinfo["/Producer"] = "Old Adobe"
    with pdf.open_metadata(set_pikepdf_as_editor=False) as metadata:
        metadata["pdf:Producer"] = "Adobe PDF Library 9.9"
        metadata["xmp:ModifyDate"] = "2020-02-26T10:35:57Z"
        metadata["dc:title"] = "Original title"
    original = BytesIO()
    pdf.save(original)
    stamped = stamp_output(original.getvalue(), "test.pdf", now=NOW)
    with pikepdf.open(BytesIO(stamped)) as result:
        assert str(result.docinfo["/Producer"]) == "Mova.io ACP 2026.9.10.7"
        assert str(result.docinfo["/ACPVersion"]) == "2026.9.10.7"
        assert str(result.docinfo["/RemediationDate"]) == "2026-09-10T04:05:06Z"
        assert str(result.docinfo["/ModDate"]) == "D:20260910040506Z"
        assert str(result.docinfo["/Title"]) == "Original title"
        assert len(result.pages) == 1
        with result.open_metadata() as metadata:
            assert metadata["pdf:Producer"] == "Mova.io ACP 2026.9.10.7"
            assert metadata["xmp:ModifyDate"] == "2026-09-10T04:05:06Z"
            assert metadata["dc:title"] == "Original title"


@pytest.mark.parametrize("ext", ["docx", "xlsx", "pptx"])
def test_office_stamp_updates_owned_properties_and_preserves_content(ext, monkeypatch):
    monkeypatch.setenv("ACP_BUILD_VERSION", "2026.9.10.7")
    original = BytesIO()
    with ZipFile(original, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        archive.writestr("docProps/core.xml", '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"/>')
        archive.writestr("document.xml", "unchanged document contents")
    stamped = stamp_output(original.getvalue(), "test." + ext, now=NOW)
    stamped = stamp_output(stamped, "test." + ext, now=NOW)
    with ZipFile(BytesIO(stamped)) as archive:
        props = ET.fromstring(archive.read("docProps/custom.xml"))
        assert len(props) == 3
        assert {p.get("name"): list(p)[0].text for p in props} == {
            "Remediated By": "Mova.io ACP", "ACP Version": "2026.9.10.7",
            "Remediation Date": "2026-09-10T04:05:06Z"}
        assert len({p.get("pid") for p in props}) == 3
        assert archive.read("document.xml") == b"unchanged document contents"
        ET.fromstring(archive.read("docProps/core.xml"))
        assert b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"' in archive.read("[Content_Types].xml")
        assert b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"' in archive.read("_rels/.rels")
        rels = ET.fromstring(archive.read("_rels/.rels"))
        assert len(rels) == 1


def test_invalid_supported_output_is_not_silently_sealed():
    with pytest.raises(Exception):
        stamp_output(b"not a PDF", "test.pdf", now=NOW)


def test_office_preserves_customer_properties_and_existing_fix_summary():
    from output_provenance import stamp_office_entries, VT_NS
    entries = {}
    stamp_office_entries(entries, ["Set language"], now=NOW, version="old")
    props = ET.fromstring(entries["docProps/custom.xml"])
    custom = ET.SubElement(props, f"{{{CUSTOM_NS}}}property", {"pid": "99", "name": "Department"})
    ET.SubElement(custom, f"{{{VT_NS}}}lpwstr").text = "Finance"
    entries["docProps/custom.xml"] = ET.tostring(props)
    stamp_office_entries(entries, now=NOW, version="new")
    props = ET.fromstring(entries["docProps/custom.xml"])
    values = {p.get("name"): list(p)[0].text for p in props}
    assert values["Department"] == "Finance"
    assert values["Fixes Applied"] == "Set language"
    assert values["ACP Version"] == "new"
    assert len(props) == 6


def test_office_package_parts_keep_default_namespaces_for_dotnet():
    """System.IO.Packaging rejects prefixed OPC Types/Relationships roots."""
    from output_provenance import stamp_office_entries
    entries = {}
    stamp_office_entries(entries, now=NOW)
    assert b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"' in entries["[Content_Types].xml"]
    assert b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"' in entries["_rels/.rels"]
