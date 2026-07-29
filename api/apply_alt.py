"""Write a reviewer-approved alt text into an Office document (WCAG 1.1.1).

The proposal lane (api/proposals.py) drafts alt text and stores it on the file's HITL row,
one proposal per image, each carrying a `locator` minted by remediate_office:

    locator = "<part name>#<cNvPr/docPr name>"      e.g. "ppt/slides/slide3.xml#Picture 4"

Approving those drafts used to store text and stop there: nothing wrote it into the document,
so the images stayed undescribed and store.mark_file_compliant_if_reviewed correctly refused
to certify the file — which left it stranded, approved but never conformant. This module is
the missing write: it resolves each locator back to its element and sets `descr`.

A reviewer may instead resolve a 1.1.1 finding by marking the image DECORATIVE — WCAG's own
exception for an image that conveys nothing. That is still a write, just not of prose: the
document must end up with an empty description AND the OOXML decorative marker, which is what
the analysers read as "deliberately undescribed" (AltTextHeuristics.IsMarkedDecorative, pinned
by tests/test_alt_text_decorative_marker.py). Leaving the image blank instead would have every
future scan re-raise the finding for the next reviewer to decide again. `apply_alt_text` takes
those locators in its `decorative` argument, alongside the prose ones, so both land in ONE
package, ONE re-scan and ONE credit — two sequential lanes could not work, since neither can
clear 1.1.1 while the other's images are still unresolved.

Deliberately narrow. It only sets a `descr` attribute (and, for decorative, an `extLst` marker)
on an element that already exists, it never adds, removes, or reorders anything, and it rewrites
only the parts it actually touched. A locator it cannot resolve is REPORTED, never guessed at —
a silently misapplied alt text is worse than an unapplied one, because a reviewer signed their
name to it.
"""
from __future__ import annotations
import io
import re
import zipfile

from formats.office.images import ALT_TARGETS as _ALT_TARGETS

# Which element carries the alt text, per part — DERIVED from the one shared table rather than
# restated, because "mirrors remediate_office" was a promise nothing enforced and it broke: when
# the xlsx entry there gained `(?:xdr:)?` to cover default-namespace drawings, this copy kept the
# prefixed-only `xdr:cNvPr`. The table that minted a locator could no longer resolve it, so a
# reviewer's approved alt text for any default-namespace workbook came back unresolved and was
# never written — the stranded approval this module exists to prevent, reintroduced by a copy.
#
# The tag may therefore be a regex ALTERNATION, not a literal; `_set_descr_in_xml` matches with
# it and rebuilds each element from the text actually found, so whichever spelling the document
# uses is preserved.
_ALT_TAG_FOR_PART = [(pat, tag) for pat, tag, _wrapper, _captions in _ALT_TARGETS]

_ATTR = lambda attrs, name: (re.search(rf'\b{name}="([^"]*)"', attrs) or [None, ""])[1]

# The OOXML "Mark as decorative" marking, byte-for-byte as Word/PowerPoint write it and exactly
# as tests/test_alt_text_decorative_marker.py builds it — that test drives the real .NET
# analysers, so this markup is verified to be what they honour rather than what we hope they do.
# Namespaces are declared INLINE on the elements we emit: a part is free to bind `a:` to nothing
# at all, and a marker written under an unbound prefix is not a marker, it is a broken document.
_DRAWINGML_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
_DECORATIVE_NS = "http://schemas.microsoft.com/office/drawing/2017/decorative"
_DECORATIVE_URI = "{C183D7F6-B498-43B3-948B-1728B52AA6E4}"
_DECORATIVE_MARK = f'<adec:decorative xmlns:adec="{_DECORATIVE_NS}" val="1"/>'
# Merged into an extLst the element already has, whose own prefix binding we cannot assume.
_DECORATIVE_EXT = (f'<a:ext xmlns:a="{_DRAWINGML_NS}" uri="{_DECORATIVE_URI}">'
                   f'{_DECORATIVE_MARK}</a:ext>')
# The whole list, when the element has none. `a:` is bound once, on the outermost element.
_DECORATIVE_EXTLST = (f'<a:extLst xmlns:a="{_DRAWINGML_NS}"><a:ext uri="{_DECORATIVE_URI}">'
                      f'{_DECORATIVE_MARK}</a:ext></a:extLst>')

# What `apply_alt_text` records as the "after" for a decorative marking. Never written into the
# document — a decorative image's description is empty, which is the whole point.
DECORATIVE_AFTER = "(marked decorative — no alt text needed)"

# Is this element ALREADY decorative? Prefix-agnostic and tolerant of `val="true"`, because the
# marker we are looking for may have been written by Word, not by us.
_HAS_MARKER = re.compile(r'decorative[^>]*\bval=["\'](?:1|true)["\']')


def _xesc(s: str) -> str:
    """Escape for an XML attribute value. A reviewer's alt text is free-form human prose —
    an unescaped quote or ampersand would corrupt the part and make the file unopenable."""
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
             .replace('"', "&quot;"))


def tag_for_part(part: str) -> str | None:
    """The alt-bearing element name in `part`, or None if that part carries no images."""
    for pat, tag in _ALT_TAG_FOR_PART:
        if pat.match(part):
            return tag
    return None


def parse_locator(locator: str) -> tuple[str, str] | None:
    """"ppt/slides/slide3.xml#Picture 4" → ("ppt/slides/slide3.xml", "Picture 4").

    Splits on the FIRST '#': a shape name may legitimately contain one, a part name cannot.
    """
    if not locator or "#" not in locator:
        return None
    part, _, name = locator.partition("#")
    part, name = part.strip(), name.strip()
    return (part, name) if part and name else None


def _set_descr_in_xml(xml: str, tag: str, name: str, alt: str) -> tuple[str, str | None]:
    """Set descr="alt" on the `tag` element whose name attribute is `name`.

    Returns (new_xml, previous_descr) — previous_descr is None when no such element exists,
    which is how the caller tells "applied" from "locator did not resolve". An empty string
    means the element was there and simply had no description, which is the normal case.
    """
    out, last, found = [], 0, None
    # `tag` is a PATTERN, not a literal — the xlsx entry is `(?:xdr:)?cNvPr`, matching both the
    # prefixed form Excel authors and the default-namespace form other generators emit. So it is
    # not re.escape'd, and the element is rebuilt from group 1 (the spelling this document
    # actually used) rather than from the pattern, which would otherwise be written into the XML.
    for m in re.finditer(rf"<({tag})\b([^>]*?)(/?)>", xml):
        real_tag, attrs, selfclose = m.group(1), m.group(2), m.group(3)
        if found is not None or _ATTR(attrs, "name").strip() != name:
            continue
        found = _ATTR(attrs, "descr")
        stripped = re.sub(r'\s*\bdescr="[^"]*"', "", attrs)   # drop any existing descr
        out.append(xml[last:m.start()])
        out.append(f'<{real_tag}{stripped} descr="{_xesc(alt)}"{selfclose}>')
        last = m.end()
    if found is None:
        return xml, None
    out.append(xml[last:])
    return "".join(out), found


def _set_decorative_in_xml(xml: str, tag: str, name: str) -> tuple[str, str | None]:
    """Mark the `tag` element named `name` decorative: drop `descr`, add the OOXML marker.

    Same (new_xml, previous_descr) contract as _set_descr_in_xml — None means the element was
    not there. An element that ALREADY carries the marker is reported as applied and left
    untouched: the document already says what the reviewer just said, and re-stating it would
    add a second marker to satisfy nobody.
    """
    m = None
    for cand in re.finditer(rf"<{re.escape(tag)}\b([^>]*?)(/?)>", xml):
        if _ATTR(cand.group(1), "name").strip() == name:
            m = cand
            break
    if m is None:
        return xml, None
    attrs, selfclose = m.group(1), m.group(2)
    # The element's full extent, so we can see (and edit) any children it already has.
    if selfclose:
        body, end = "", m.end()
    else:
        close = re.compile(rf"</{re.escape(tag)}>").search(xml, m.end())
        if not close:
            return xml, None                    # malformed part: report, never guess
        body, end = xml[m.end():close.start()], close.end()

    before = _ATTR(attrs, "descr")
    if _HAS_MARKER.search(body):
        return xml, before                      # already decorative — nothing to write
    stripped = re.sub(r'\s*\bdescr="[^"]*"', "", attrs)   # a decorative image has NO description
    # An element may already carry an extLst (a shape id, a creation id …). OOXML allows one, so
    # merge our ext into it rather than emitting a second list that would invalidate the part.
    lst = re.search(r"<((?:\w+:)?)extLst\b[^>]*?(/?)>", body)
    if lst is None:
        new_body = body + _DECORATIVE_EXTLST
    elif lst.group(2):                          # <a:extLst/> — empty, expand it around our ext
        new_body = (body[:lst.start()] + f"<{lst.group(1)}extLst>{_DECORATIVE_EXT}"
                    f"</{lst.group(1)}extLst>" + body[lst.end():])
    else:
        close_lst = body.find(f"</{lst.group(1)}extLst>", lst.end())
        if close_lst == -1:
            return xml, None
        new_body = body[:close_lst] + _DECORATIVE_EXT + body[close_lst:]
    return xml[:m.start()] + f"<{tag}{stripped}>{new_body}</{tag}>" + xml[end:], before


def apply_alt_text(data: bytes, values: dict[str, str],
                   decorative: list[str] | None = None) -> tuple[bytes, list[dict], list[str]]:
    """Write each locator's approved alt text into the Office package `data`.

    values: {locator: alt text}. Returns (new_bytes, applied, unresolved):
      applied    — [{locator, before, after}], one per element actually written, in the
                   caller's order, ready for store.record_remediation_diffs.
      unresolved — locators whose part or element was not found. The caller must surface
                   these rather than treating the approval as honoured.

    decorative: locators a reviewer resolved as decorative (WCAG 1.1.1's exception). Each gets
    an EMPTY description plus the OOXML decorative marker, never prose — see the module
    docstring. They ride in the same call as `values` on purpose: a decorative image and a
    described one on the same slide are one document edit, verified by one re-scan. A locator
    named in both is written decorative, because the reviewer's exception is the later, more
    specific judgement about that image.

    When nothing resolves, the ORIGINAL bytes are returned unchanged — never a rezipped
    copy that differs only by compression, which would look like a modified document.
    """
    values = {k: v for k, v in (values or {}).items() if v and v.strip()}
    deco = {k for k in (decorative or []) if k and k.strip()}
    values = {k: v for k, v in values.items() if k not in deco}
    if not values and not deco:
        return data, [], []

    with zipfile.ZipFile(io.BytesIO(data)) as zin:
        names = zin.namelist()
        entries = {n: zin.read(n) for n in names}

    # Group by part so each XML part is parsed and rewritten once, not once per image.
    by_part: dict[str, list[tuple[str, str, str | None]]] = {}  # part → [(locator, name, alt|None)]
    unresolved: list[str] = []
    for locator, alt in list(values.items()) + [(k, None) for k in deco]:
        parsed = parse_locator(locator)
        if not parsed or parsed[0] not in entries or not tag_for_part(parsed[0]):
            unresolved.append(locator)
            continue
        by_part.setdefault(parsed[0], []).append((locator, parsed[1], alt))

    applied: list[dict] = []
    touched: dict[str, bytes] = {}
    for part, targets in by_part.items():
        tag = tag_for_part(part)
        try:
            xml = entries[part].decode("utf-8")
        except UnicodeDecodeError:
            unresolved.extend(loc for loc, _, _ in targets)
            continue
        for locator, name, alt in targets:
            if alt is None:
                xml, before = _set_decorative_in_xml(xml, tag, name)
            else:
                xml, before = _set_descr_in_xml(xml, tag, name, alt)
            if before is None:
                unresolved.append(locator)                  # element gone: report, never guess
                continue
            applied.append({"locator": locator,
                            "before": before or "(no alt text)",
                            "after": DECORATIVE_AFTER if alt is None else alt})
        touched[part] = xml.encode("utf-8")

    if not applied:
        return data, [], unresolved

    entries.update(touched)
    buf = io.BytesIO()
    # Rewrite every entry in its original order. OPC readers tolerate reordering, but a
    # diff of the package should show only the parts that changed.
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zout:
        for n in names:
            zout.writestr(n, entries[n])
    return buf.getvalue(), applied, unresolved
