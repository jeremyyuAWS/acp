"""Write reviewer-approved slide titles into a pptx file (WCAG 2.4.6).

api/proposals.propose_slide_titles drafts titles for slides whose title placeholder
exists but was left empty, keyed by locator:

    locator = 'slide <N>'    e.g. 'slide 1'

This is the write-back: approved titles fill the empty placeholder's text body.
Only slides with an existing title placeholder are touched — a slide whose layout
has no title slot by design is never modified, consistent with the proposer which
skips those slides too.
"""
from __future__ import annotations

import io
import re
import zipfile
from copy import deepcopy
from lxml import etree

# "slide 1", "slide 12" etc.
_SLIDE_LOC = re.compile(r"^slide\s+(\d+)$", re.IGNORECASE)

# Both ordinary and centred titles match the detector's placeholder types.
_NS = {'p': 'http://schemas.openxmlformats.org/presentationml/2006/main',
       'a': 'http://schemas.openxmlformats.org/drawingml/2006/main'}


def _fill_empty_title(content: bytes, text: str) -> bytes | None:
    """Change exactly one empty title, retaining layout, language and run styling.

    A regex beginning at a preceding body shape can cross into the title shape,
    replacing the body's first text instead. Select the actual placeholder node.
    Existing text is a stale approval, and multiple title slots are ambiguous.
    """
    try:
        root = etree.fromstring(content, etree.XMLParser(resolve_entities=False, no_network=True))
        titles = root.xpath('.//p:sp[p:nvSpPr/p:nvPr/p:ph[@type="title" or @type="ctrTitle"]]', namespaces=_NS)
        if len(titles) != 1:
            return None
        body = titles[0].find('p:txBody', _NS)
        if body is None:
            return None
        # Fields and breaks are meaningful content, not an empty placeholder.
        if body.xpath('.//a:fld | .//a:br', namespaces=_NS):
            return None
        current = ''.join(body.xpath('.//a:t/text()', namespaces=_NS))
        # The writer may have uploaded before its database transaction rolled
        # back. Replaying the exact approved value is a successful no-op.
        if current == text:
            return content
        if current.strip():
            return None
        nodes = body.xpath('.//a:t', namespaces=_NS)
        if nodes:
            nodes[0].text = text
        else:
            paragraph = body.find('a:p', _NS)
            if paragraph is None:
                paragraph = etree.SubElement(body, '{' + _NS['a'] + '}p')
            run = etree.Element('{' + _NS['a'] + '}r')
            end = paragraph.find('a:endParaRPr', _NS)
            if end is not None:
                properties = deepcopy(end)
                properties.tag = '{' + _NS['a'] + '}rPr'
                run.append(properties)
            etree.SubElement(run, '{' + _NS['a'] + '}t').text = text
            paragraph.insert(list(paragraph).index(end) if end is not None else len(paragraph), run)
        result = etree.tostring(root, encoding='utf-8')
        reopened = etree.fromstring(result)
        actual = reopened.xpath('.//p:sp[p:nvSpPr/p:nvPr/p:ph[@type="title" or @type="ctrTitle"]]/p:txBody//a:t/text()', namespaces=_NS)
        return result if ''.join(actual).strip() == text.strip() else None
    except (etree.XMLSyntaxError, ValueError):
        return None


def apply_pptx_slide_titles(
    data: bytes, values: dict[str, str]
) -> tuple[bytes, list[dict], list[str]]:
    """Fill approved slide titles into the pptx zip.

    `values` maps "slide N" locators to approved title strings.
    Returns (fixed_bytes, applied, unresolved).
    applied entries: {locator, before, after}.
    unresolved: locators present in values but not found/matched in the document.
    """
    if not values:
        return data, [], []

    # Parse locators → {slide_num: title}
    to_write: dict[int, str] = {}
    unresolved: list[str] = []
    for locator, title in values.items():
        m = _SLIDE_LOC.match(locator.strip())
        if m and isinstance(title, str) and title.strip():
            to_write[int(m.group(1))] = title
        else:
            unresolved.append(locator)

    if not to_write:
        return data, [], unresolved

    applied: list[dict] = []
    changed = False
    in_buf = io.BytesIO(data)
    out_buf = io.BytesIO()

    with zipfile.ZipFile(in_buf, "r") as zin, \
         zipfile.ZipFile(out_buf, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            content = zin.read(info.filename)
            sm = re.fullmatch(r"ppt/slides/slide(\d+)\.xml", info.filename)
            if sm:
                num = int(sm.group(1))
                if num in to_write:
                    title = to_write.pop(num)
                    new_content = _fill_empty_title(content, title)
                    if new_content is not None:
                        changed = changed or new_content != content
                        content = new_content
                        applied.append({
                            "locator": f"slide {num}",
                            "before": "(empty title placeholder)",
                            "after": title,
                        })
                    else:
                        unresolved.append(f"slide {num}")
            zout.writestr(info, content)

    # Slide numbers named in values but absent from the zip
    for num in to_write:
        unresolved.append(f"slide {num}")

    return out_buf.getvalue() if changed else data, applied, unresolved
