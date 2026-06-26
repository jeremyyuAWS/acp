"""Server-side Office remediation (ADR 0005 step 4 — docx/pptx/xlsx).

The vendored DigitalA11y .NET engine flags Office accessibility issues but is
scan-only — there's no Office remediator to wrap. So this implements the two
DETERMINISTIC Office fixes directly, in pure stdlib (no new dependency):

  * document language  → dc:language in docProps/core.xml  (the exact thing the
                         .NET DocumentLanguageRule reads: PackageProperties.Language)
  * document title     → dc:title    in docProps/core.xml  (DocumentTitleRule reads
                         PackageProperties.Title)

OOXML files are zip archives of XML; the OPC core-properties part is identical
across docx/pptx/xlsx, so one code path covers all three. Anything needing
content judgement (alt text, reading order, contrast) is NOT touched here and
routes to human review — same contract as the HTML/PDF remediators.
"""
from __future__ import annotations
import os
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

_CORE = "docProps/core.xml"
_CUSTOM = "docProps/custom.xml"
_FMTID = "{D5CDD505-2E9C-101B-9397-08002B2CF9AE}"  # standard OPC custom-properties GUID
TOOL = "Mova.io ACP"
VERSION = os.environ.get("ACP_VERSION", "2026.06")


def _xesc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _stamp_provenance(entries: dict, applied: list[str]) -> None:
    """Write a remediation provenance stamp into docProps/custom.xml — shows in the
    'Custom' tab of the file's Properties: who/what fixed it, the standard, the date,
    and the fixes applied. Creates the part (+ content-type + relationship) if absent,
    or appends to an existing custom-properties part."""
    props = [
        ("Remediated By", TOOL),
        ("ACP Version", VERSION),
        ("Remediation Date", datetime.now(timezone.utc).strftime("%Y-%m-%d")),
        ("WCAG Target", "WCAG 2.1 AA"),
        ("Fixes Applied", "; ".join(applied)[:255]),
    ]
    if _CUSTOM in entries:  # append, continuing the pid sequence; part already declared
        xml = entries[_CUSTOM].decode("utf-8", "replace")
        pids = [int(m) for m in re.findall(r'pid="(\d+)"', xml)]
        start = (max(pids) + 1) if pids else 2
        frag = "".join(
            f'<property fmtid="{_FMTID}" pid="{start + i}" name="{_xesc(n)}">'
            f'<vt:lpwstr>{_xesc(v)}</vt:lpwstr></property>'
            for i, (n, v) in enumerate(props))
        entries[_CUSTOM] = xml.replace("</Properties>", frag + "</Properties>").encode("utf-8")
        return
    body = "".join(
        f'<property fmtid="{_FMTID}" pid="{2 + i}" name="{_xesc(n)}">'
        f'<vt:lpwstr>{_xesc(v)}</vt:lpwstr></property>'
        for i, (n, v) in enumerate(props))
    entries[_CUSTOM] = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n'
        '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/custom-properties" '
        'xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">'
        + body + '</Properties>').encode("utf-8")
    ct = "[Content_Types].xml"
    if ct in entries and "docProps/custom.xml" not in entries[ct].decode("utf-8", "replace"):
        ov = ('<Override PartName="/docProps/custom.xml" '
              'ContentType="application/vnd.openxmlformats-officedocument.custom-properties+xml"/>')
        entries[ct] = entries[ct].decode("utf-8").replace("</Types>", ov + "</Types>").encode("utf-8")
    rels = "_rels/.rels"
    if rels in entries and "custom-properties" not in entries[rels].decode("utf-8", "replace"):
        rel = ('<Relationship Id="rIdACPprov" '
               'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/custom-properties" '
               'Target="docProps/custom.xml"/>')
        entries[rels] = entries[rels].decode("utf-8").replace("</Relationships>", rel + "</Relationships>").encode("utf-8")
_CP = "http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
_DC = "http://purl.org/dc/elements/1.1/"
_NS = {
    "cp": _CP, "dc": _DC,
    "dcterms": "http://purl.org/dc/terms/",
    "dcmitype": "http://purl.org/dc/dcmitype/",
    "xsi": "http://www.w3.org/2001/XMLSchema-instance",
}


def remediate_office(path: Path, *, lang: str = "en-US"):
    """Apply deterministic Office accessibility fixes to a copy of the file.

    Returns (fixed_path, applied, skipped). fixed_path is None if nothing applied.
    """
    try:
        with zipfile.ZipFile(path) as zin:
            names = zin.namelist()
            if _CORE not in names:
                return None, [], ["no OPC core-properties part — cannot set language/title"]
            entries = {n: zin.read(n) for n in names}
    except Exception as e:
        return None, [], [f"could not open Office file: {type(e).__name__}"]

    for pfx, uri in _NS.items():
        ET.register_namespace(pfx, uri)
    root = ET.fromstring(entries[_CORE].decode("utf-8"))
    applied: list[str] = []

    def _ensure(tag_uri: str, tag: str, value: str, label: str):
        el = root.find(f"{{{tag_uri}}}{tag}")
        if el is None or not (el.text or "").strip():
            if el is None:
                el = ET.SubElement(root, f"{{{tag_uri}}}{tag}")
            el.text = value
            applied.append(label.format(value=value))

    _ensure(_DC, "language", lang, "Set document language to '{value}'")
    # A meaningful title beats an empty one; derive a readable default from the name.
    title = path.stem.replace("-", " ").replace("_", " ").strip() or "Document"
    _ensure(_DC, "title", title, "Set document title to '{value}'")

    if not applied:
        return None, [], ["language and title already set"]

    # Also stamp the STANDARD (visible) core properties: the remediation date as the
    # Modified date + "Last saved by" — so it shows on the General tab, not only Custom.
    _DCTERMS, _XSI = _NS["dcterms"], _NS["xsi"]
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lmb = root.find(f"{{{_CP}}}lastModifiedBy")
    if lmb is None:
        lmb = ET.SubElement(root, f"{{{_CP}}}lastModifiedBy")
    lmb.text = TOOL
    mod = root.find(f"{{{_DCTERMS}}}modified")
    if mod is None:
        mod = ET.SubElement(root, f"{{{_DCTERMS}}}modified")
    mod.set(f"{{{_XSI}}}type", "dcterms:W3CDTF")
    mod.text = ts

    new_core = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n'
                + ET.tostring(root, encoding="unicode"))
    entries[_CORE] = new_core.encode("utf-8")

    # Tamper-evident provenance in the Custom-properties tab (who/what/when/standard).
    _stamp_provenance(entries, applied)

    out_path = path.with_name(f"remediated-{path.name}")
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zout:
        for name, data in entries.items():           # preserves archive order
            zout.writestr(name, data)
    return out_path, applied, []
