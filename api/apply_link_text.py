"""Write a reviewer-approved link text into an Office document (WCAG 2.4.4 / 2.4.9).

api/proposals.propose_link_texts drafts descriptive link text, keyed by

    locator = href      (the hyperlink's resolved destination URL)

not a part#name pair like apply_alt.py's image locator — the same vague or duplicate text
can legitimately appear on more than one run pointing at the same destination, and all of
them need the same fix. Approving those drafts used to store the text and stop there:
nothing wrote it into the document, so store.mark_file_compliant_if_reviewed correctly
refused to certify the file (proposals.py's own docstring at the time called this out as
the known gap). This module is the missing write.

Known, deliberate limitation: because the locator is the href alone, two DIFFERENT vague
texts that happen to point at the SAME destination collapse onto one {locator: value} entry
— the later approval wins. This mirrors the exact granularity proposals.propose_link_texts
already dedupes proposals at (one proposal per distinct (normalized text, href) pair sharing
a single href-keyed value store), so it is not a new risk introduced here, just an existing
one this module inherits. A rarer case in practice than the alt-text one-image-one-locator
case apply_alt.py handles.

Deliberately narrow otherwise: it rewrites the display text of every hyperlink run/cell whose
resolved href matches an approved locator, and touches nothing else — no destination change,
no reordering. A part it cannot resolve is REPORTED, never guessed at.
"""
from __future__ import annotations
import io
import re
import zipfile

import office_structure as _os


def _xesc_text(s: str) -> str:
    """Escape for XML element text content — a reviewer's link text is free-form prose."""
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _xesc_attr(s: str) -> str:
    return _xesc_text(s).replace('"', "&quot;")


def _apply_docx(xml: str, rels: dict[str, str], values: dict[str, str]) -> tuple[str, list[dict]]:
    applied: list[dict] = []
    out, last = [], 0
    for m in re.finditer(r'(<w:hyperlink[^>]*r:id="(rId\w+)"[^>]*>)(.*?)(</w:hyperlink>)', xml, re.S):
        href = rels.get(m.group(2))
        if not href or href not in values:
            continue
        inner = m.group(3)
        before = "".join(_os._WT.findall(inner))
        after = values[href]
        rpr_m = re.search(r"<w:rPr\b[^>]*/>|<w:rPr\b[^>]*>.*?</w:rPr>", inner, re.S)
        rpr = rpr_m.group(0) if rpr_m else ""
        new_inner = f'<w:r>{rpr}<w:t xml:space="preserve">{_xesc_text(after)}</w:t></w:r>'
        out.append(xml[last:m.start()])
        out.append(m.group(1) + new_inner + m.group(4))
        last = m.end()
        applied.append({"locator": href, "before": before or "(empty link text)", "after": after})
    out.append(xml[last:])
    return "".join(out), applied


def _apply_pptx(xml: str, rels: dict[str, str], values: dict[str, str]) -> tuple[str, list[dict]]:
    applied: list[dict] = []
    out, last = [], 0
    for m in re.finditer(r"(<a:r>)(.*?)(</a:r>)", xml, re.S):
        inner = m.group(2)
        hm = _os._A_HLINK.search(inner)
        if not hm:
            continue
        href = rels.get(hm.group(1))
        if not href or href not in values:
            continue
        before = "".join(_os._AT.findall(inner))
        after = values[href]
        rpr_m = re.search(r"<a:rPr\b[^>]*/>|<a:rPr\b[^>]*>.*?</a:rPr>", inner, re.S)
        rpr = rpr_m.group(0) if rpr_m else ""
        new_inner = f'{rpr}<a:t>{_xesc_text(after)}</a:t>'
        out.append(xml[last:m.start()])
        out.append(m.group(1) + new_inner + m.group(3))
        last = m.end()
        applied.append({"locator": href, "before": before or "(empty link text)", "after": after})
    out.append(xml[last:])
    return "".join(out), applied


def _apply_xlsx(xml: str, rels: dict[str, str], values: dict[str, str]) -> tuple[str, list[dict]]:
    applied: list[dict] = []
    out, last = [], 0
    for m in re.finditer(r"<hyperlink\b[^>]*/?>", xml):
        tag = m.group(0)
        rid_m = re.search(r'r:id="(rId\w+)"', tag)
        if not rid_m:
            continue
        href = rels.get(rid_m.group(1))
        if not href or href not in values:
            continue
        disp_m = _os._HL_DISPLAY.search(tag)
        before = disp_m.group(1) if disp_m else ""
        after = values[href]
        if disp_m:
            new_tag = tag[:disp_m.start()] + f'display="{_xesc_attr(after)}"' + tag[disp_m.end():]
        else:
            new_tag = tag[:-1].rstrip("/") + f' display="{_xesc_attr(after)}"/>' if tag.endswith("/>") \
                else tag[:-1] + f' display="{_xesc_attr(after)}">'
        out.append(xml[last:m.start()])
        out.append(new_tag)
        last = m.end()
        applied.append({"locator": href, "before": before or "(empty link text)", "after": after})
    out.append(xml[last:])
    return "".join(out), applied


def apply_link_text(data: bytes, ext: str, values: dict[str, str]) -> tuple[bytes, list[dict], list[str]]:
    """Write each locator's (href's) approved link text into the Office package `data`.

    values: {href: link text}. Returns (new_bytes, applied, unresolved):
      applied    — [{locator, before, after}], one per hyperlink run/cell actually rewritten,
                   ready for store.record_remediation_diffs.
      unresolved — hrefs that matched no hyperlink anywhere in the document. The caller must
                   surface these rather than treating the approval as honoured.

    When nothing resolves, the ORIGINAL bytes are returned unchanged.
    """
    ext = (ext or "").lower().lstrip(".")
    values = {k: v for k, v in (values or {}).items() if k and v and v.strip()}
    if not values or ext not in ("docx", "pptx", "xlsx"):
        return data, [], list(values.keys()) if ext not in ("docx", "pptx", "xlsx") else []

    with zipfile.ZipFile(io.BytesIO(data)) as zin:
        names = zin.namelist()
        entries = {n: zin.read(n) for n in names}

    applied: list[dict] = []
    touched: dict[str, bytes] = {}
    remaining = dict(values)

    if ext == "docx":
        part = "word/document.xml"
        if part in entries:
            try:
                xml = entries[part].decode("utf-8")
                rels = _os._relationships(zipfile.ZipFile(io.BytesIO(data)), "word/_rels/document.xml.rels")
                new_xml, part_applied = _apply_docx(xml, rels, remaining)
                if part_applied:
                    touched[part] = new_xml.encode("utf-8")
                    applied.extend(part_applied)
            except UnicodeDecodeError:
                pass
    elif ext == "pptx":
        for slide_name in sorted(n for n in names if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)):
            num = re.search(r"slide(\d+)\.xml", slide_name).group(1)
            try:
                xml = entries[slide_name].decode("utf-8")
            except UnicodeDecodeError:
                continue
            rels = _os._relationships(zipfile.ZipFile(io.BytesIO(data)), f"ppt/slides/_rels/slide{num}.xml.rels")
            new_xml, part_applied = _apply_pptx(xml, rels, remaining)
            if part_applied:
                touched[slide_name] = new_xml.encode("utf-8")
                applied.extend(part_applied)
    elif ext == "xlsx":
        for ws_name in sorted(n for n in names if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n)):
            num = re.search(r"sheet(\d+)\.xml", ws_name).group(1)
            try:
                xml = entries[ws_name].decode("utf-8")
            except UnicodeDecodeError:
                continue
            rels = _os._relationships(zipfile.ZipFile(io.BytesIO(data)), f"xl/worksheets/_rels/sheet{num}.xml.rels")
            new_xml, part_applied = _apply_xlsx(xml, rels, remaining)
            if part_applied:
                touched[ws_name] = new_xml.encode("utf-8")
                applied.extend(part_applied)

    unresolved = [href for href in values if href not in {a["locator"] for a in applied}]

    if not applied:
        return data, [], unresolved

    entries.update(touched)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zout:
        for n in names:
            zout.writestr(n, entries[n])
    return buf.getvalue(), applied, unresolved
