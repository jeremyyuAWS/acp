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
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

_CORE = "docProps/core.xml"
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

    new_core = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n'
                + ET.tostring(root, encoding="unicode"))
    entries[_CORE] = new_core.encode("utf-8")

    out_path = path.with_name(f"remediated-{path.name}")
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zout:
        for name, data in entries.items():           # preserves archive order
            zout.writestr(name, data)
    return out_path, applied, []
