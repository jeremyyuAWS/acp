"""Embedded provenance for saved remediation artifacts, before evidence is sealed.

A stamp records ACP processing, never a claim that all accessibility issues passed.
Keep XMP and PDF document information synchronized: viewers may prefer either.
"""
from datetime import datetime, timezone
from io import BytesIO
import os
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile, ZIP_DEFLATED

TOOL = "Mova.io ACP"
CUSTOM_NS = "http://schemas.openxmlformats.org/officeDocument/2006/custom-properties"
VT_NS = "http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes"
CP_NS = "http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
DCT_NS = "http://purl.org/dc/terms/"


def _version():
    return os.environ.get("ACP_BUILD_VERSION") or os.environ.get("ACP_VERSION") or "dev"


def stamp_office_entries(entries, applied=None, *, now=None, version=None):
    now = now or datetime.now(timezone.utc)
    timestamp = now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    custom_path = "docProps/custom.xml"
    root = ET.fromstring(entries[custom_path]) if custom_path in entries else ET.Element(f"{{{CUSTOM_NS}}}Properties")
    values = {"Remediated By": TOOL, "ACP Version": version or _version(),
              "Remediation Date": timestamp}
    if applied is not None:
        values.update({"WCAG Target": "WCAG 2.1 AA", "Fixes Applied": "; ".join(applied)[:255]})
    # Refresh owned properties, preserving customer fields and previous fix summaries.
    for child in list(root):
        if child.get("name") in values:
            root.remove(child)
    pid = max([int(p.get("pid", "1")) for p in root] + [1]) + 1
    for index, (name, value) in enumerate(values.items()):
        prop = ET.SubElement(root, f"{{{CUSTOM_NS}}}property", {
            "fmtid": "{D5CDD505-2E9C-101B-9397-08002B2CF9AE}", "pid": str(pid + index), "name": name})
        ET.SubElement(prop, f"{{{VT_NS}}}lpwstr").text = value
    ET.register_namespace("vt", VT_NS)
    entries[custom_path] = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    ct_ns = "http://schemas.openxmlformats.org/package/2006/content-types"
    ct = (ET.fromstring(entries["[Content_Types].xml"]) if "[Content_Types].xml" in entries
          else ET.Element(f"{{{ct_ns}}}Types"))
    if not any(p.get("PartName") == "/docProps/custom.xml" for p in ct):
        ET.SubElement(ct, f"{{{ct_ns}}}Override", {"PartName": "/docProps/custom.xml", "ContentType": "application/vnd.openxmlformats-officedocument.custom-properties+xml"})
    ET.register_namespace("", ct_ns)
    entries["[Content_Types].xml"] = ET.tostring(ct, encoding="utf-8", xml_declaration=True)
    rel_ns = "http://schemas.openxmlformats.org/package/2006/relationships"
    rels = ET.fromstring(entries["_rels/.rels"]) if "_rels/.rels" in entries else ET.Element(f"{{{rel_ns}}}Relationships")
    rel_type = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/custom-properties"
    if not any(p.get("Type") == rel_type for p in rels):
        ids = {p.get("Id") for p in rels}
        rid = "rIdACPprov"
        while rid in ids:
            rid += "_"
        ET.SubElement(rels, f"{{{rel_ns}}}Relationship", {"Id": rid, "Type": rel_type, "Target": custom_path})
    ET.register_namespace("", rel_ns)
    entries["_rels/.rels"] = ET.tostring(rels, encoding="utf-8", xml_declaration=True)
    if "docProps/core.xml" in entries:
        core = ET.fromstring(entries["docProps/core.xml"])
        for tag, value in ((f"{{{CP_NS}}}lastModifiedBy", TOOL), (f"{{{DCT_NS}}}modified", timestamp)):
            el = core.find(tag)
            if el is None:
                el = ET.SubElement(core, tag)
            el.text = value
            if tag.endswith("modified"):
                el.set("{http://www.w3.org/2001/XMLSchema-instance}type", "dcterms:W3CDTF")
        # xsi:type is a QName: its dcterms prefix must be bound even if ET chose ns1.
        ET.register_namespace("dcterms", DCT_NS)
        entries["docProps/core.xml"] = ET.tostring(core, encoding="utf-8", xml_declaration=True)


def stamp_output(data: bytes, filename: str, *, now=None) -> bytes:
    """Stamp a supported saved copy, raising on failure rather than sealing unstamped bytes."""
    ext = Path(filename).suffix.lower()
    if ext not in {".pdf", ".docx", ".xlsx", ".pptx"}:
        return data
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    timestamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    if ext == ".pdf":
        import pikepdf
        with pikepdf.open(BytesIO(data)) as pdf:
            with pdf.open_metadata(set_pikepdf_as_editor=False, update_docinfo=False) as xmp:
                xmp["pdf:Producer"] = f"{TOOL} {_version()}"
                xmp["xmp:ModifyDate"] = timestamp
                xmp["xmp:MetadataDate"] = timestamp
            pdf.docinfo["/Producer"] = f"{TOOL} {_version()}"
            pdf.docinfo["/RemediatedBy"] = TOOL
            pdf.docinfo["/ACPVersion"] = _version()
            pdf.docinfo["/RemediationDate"] = timestamp
            pdf.docinfo["/ModDate"] = now.strftime("D:%Y%m%d%H%M%SZ")
            out = BytesIO()
            pdf.save(out)
            return out.getvalue()
    with ZipFile(BytesIO(data)) as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
    stamp_office_entries(entries, now=now)
    out = BytesIO()
    with ZipFile(out, "w", ZIP_DEFLATED) as archive:
        for name, value in entries.items():
            archive.writestr(name, value)
    return out.getvalue()
