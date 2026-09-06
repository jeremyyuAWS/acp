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

# "slide 1", "slide 12" etc.
_SLIDE_LOC = re.compile(r"^slide\s+(\d+)$", re.IGNORECASE)

# A pptx title placeholder shape block.  The type="title" attr may be single or
# double quoted, and the ph element may appear before or after other children of
# nvSpPr, so we match the whole <p:sp>…</p:sp> by presence of the ph type marker.
_TITLE_SP = re.compile(
    r"<p:sp\b[^>]*>.*?<p:ph[^>]+type=[\"']title[\"'][^>]*/?>.*?</p:sp>",
    re.DOTALL,
)

# The text body inside a shape.
_TXBODY = re.compile(r"(<p:txBody\b[^>]*>)(.*?)(</p:txBody>)", re.DOTALL)


def _xesc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _rewrite_txbody(sp_xml: str, text: str) -> str:
    """Replace whatever text runs are in the title shape's txBody with `text`."""
    def _replace(m):
        open_tag, _, close_tag = m.group(1), m.group(2), m.group(3)
        new_run = f'<a:p><a:r><a:rPr lang="en-US"/><a:t>{_xesc(text)}</a:t></a:r></a:p>'
        return f"{open_tag}<a:bodyPr/><a:lstStyle/>{new_run}{close_tag}"
    return _TXBODY.sub(_replace, sp_xml, count=1)


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
        if m:
            to_write[int(m.group(1))] = title
        else:
            unresolved.append(locator)

    if not to_write:
        return data, [], unresolved

    applied: list[dict] = []
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
                    xml = content.decode("utf-8", "replace")
                    rewrote = [False]

                    def _rewrite(m, _t=title, _flag=rewrote):
                        result = _rewrite_txbody(m.group(0), _t)
                        _flag[0] = True
                        return result

                    new_xml = _TITLE_SP.sub(_rewrite, xml, count=1)
                    if rewrote[0]:
                        content = new_xml.encode("utf-8")
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

    return out_buf.getvalue(), applied, unresolved
