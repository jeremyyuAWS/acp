"""Write a reviewer-approved alt text into an Office document (WCAG 1.1.1).

The proposal lane (api/proposals.py) drafts alt text and stores it on the file's HITL row,
one proposal per image, each carrying a `locator` minted by remediate_office. There are TWO
kinds of fragment, because the proposers reach an image in two different ways:

    "<part>#<cNvPr/docPr name>"   e.g. "ppt/slides/slide3.xml#Picture 4"
    "<part>#<r:embed id>"         e.g. "ppt/slides/slide3.xml#rId2"

A proposer that read the image's BYTES — the vision alt draft, the xlsx chart-data draft, the
evidence thumbnail — got there through the blip's relationship id (remediate_office's
`_image_bytes_for`), and mints that id. Only the decorative-inference branch, which never opens
the image, names the element.

This module used to understand names alone, so every rId locator missed: `_set_descr_in_xml`
looked for an element named "rId2", found none, and reported it unresolved. That is the whole
vision alt-text lane — the flagship AI-drafts / human-approves path for Office images. The
reviewer's description was stored, counted by store.count_unapplied_approved_values as content
the document owed, handed here, dropped, and the row was never marked applied: the file could
never certify or reach Publish. Silent, because an unresolved locator is (correctly) only
logged, and because tests/test_apply_approved_values.py seeds NAME locators, so no test ever
fed this module what the proposers actually emit.

`resolve_target` now understands both, by walking the blips: within a pic/drawing block the
alt-bearing element precedes its `<a:blip r:embed>`, which is the same adjacency
`_image_bytes_for` relies on to find the image in the first place. Resolving here rather than
re-minting locators at proposal time is deliberate — it repairs rows already sitting approved
in the database, which a change at the source could not reach.

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
#
# IMPORTED, not redeclared. This module and the 1.1.1 detector must answer "is this decorative?"
# identically — a disagreement means either a conforming image is flagged forever (detector says
# no, remediator says yes, so nothing is ever written to clear it) or an undescribed one
# certifies. They were separate expressions until one of them turned out to be a substring test
# that could not match the marker THIS module writes, and the first failure mode duly happened.
# One expression, one import; drift is now a syntax error rather than a silent policy change.
from formats.office.images import _DECORATIVE_MARKER as _HAS_MARKER  # noqa: E402

# The relationship reference on a drawing's blip — how a bytes-reading proposer identified the
# image, and so what its locator says. Kept loose (any id, not just `rId\d+`) because the value
# we compare against is one WE minted from this same attribute; a stricter pattern here could
# only ever reject a locator that is in fact correct.
_R_EMBED = re.compile(r'\br:embed="([^"]+)"')


def _xesc(s: str) -> str:
    """Escape for an XML attribute value. A reviewer's alt text is free-form human prose —
    an unescaped quote or ampersand would corrupt the part and make the file unopenable."""
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
             .replace('"', "&quot;"))


def tag_for_part(part: str) -> str | None:
    """Regex for the alt-bearing element in `part`, or None if that part carries no images.

    A PATTERN, not a literal tag — one part may carry either namespace flavour of the same
    element. Callers must take the tag they actually rewrite from the match, never from this.
    """
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


def _alt_elements(xml: str, tag: str) -> list[re.Match]:
    """Every alt-bearing element in the part, in document order.

    `tag` is a pattern (see _ALT_TAG_FOR_PART), so group 1 is the tag text as this document
    actually spells it — `xdr:cNvPr` or bare `cNvPr`. Groups: (tag, attrs, self-closing slash).
    """
    return list(re.finditer(rf"<({tag})\b([^>]*?)(/?)>", xml))


def resolve_target(xml: str, tag: str, fragment: str) -> int | None:
    """Offset of the element a locator fragment addresses, or None if nothing does.

    Two fragment kinds, tried in that order (see the module docstring for why both exist):

      NAME     — the element's own `name` attribute. First match wins, which is the behaviour
                 this module always had; a part with two shapes of one name is a document we
                 cannot disambiguate, and picking the first is at least stable.
      r:embed  — the relationship id of the image the element describes. Within a pic/drawing
                 block the alt-bearing element comes first and its `<a:blip r:embed>` follows,
                 so an element owns the first blip between it and the NEXT such element. A
                 shape with no image of its own (a group's cNvPr, a slide's root cNvPr) has no
                 blip before the next element and simply matches nothing.

    Name is tried first so a document that literally names a shape "rId2" still resolves to the
    shape the reviewer was looking at, not to whatever image carries that relationship.
    """
    els = _alt_elements(xml, tag)
    for m in els:
        if _ATTR(m.group(2), "name").strip() == fragment:
            return m.start()
    for i, m in enumerate(els):
        stop = els[i + 1].start() if i + 1 < len(els) else len(xml)
        blip = _R_EMBED.search(xml, m.end(), stop)
        if blip and blip.group(1) == fragment:
            return m.start()
    return None


def _set_descr_in_xml(xml: str, tag: str, at: int, alt: str) -> tuple[str, str | None]:
    """Set descr="alt" on the alt-bearing element starting at offset `at` (from resolve_target).

    Returns (new_xml, previous_descr) — previous_descr is None when no such element exists,
    which is how the caller tells "applied" from "locator did not resolve". An empty string
    means the element was there and simply had no description, which is the normal case.

    Targeted by OFFSET rather than by name because a locator may name no element at all (an
    r:embed id names an image, not a shape). resolve_target answers "which element", once and
    for both fragment kinds; this only writes.
    """
    m = re.compile(rf"<({tag})\b([^>]*?)(/?)>").match(xml, at)
    if not m:
        return xml, None
    # The tag as THIS document spells it, never the pattern — rebuilding from the pattern would
    # write a literal `(?:xdr:)?cNvPr` element into the part.
    real_tag, attrs, selfclose = m.group(1), m.group(2), m.group(3)
    found = _ATTR(attrs, "descr")
    stripped = re.sub(r'\s*\bdescr="[^"]*"', "", attrs)   # drop any existing descr
    return (xml[:m.start()] + f'<{real_tag}{stripped} descr="{_xesc(alt)}"{selfclose}>'
            + xml[m.end():]), found


def _set_decorative_in_xml(xml: str, tag: str, at: int) -> tuple[str, str | None]:
    """Mark the element at offset `at` decorative: drop `descr`, add the OOXML marker.

    Same (new_xml, previous_descr) contract as _set_descr_in_xml, and targeted the same way —
    by offset, from resolve_target, so a decorative resolution reaches its image whether the
    locator names the shape or the shape's r:embed relationship.

    An element that ALREADY carries the marker is reported as applied and left untouched: the
    document already says what the reviewer just said, and re-stating it would add a second
    marker to satisfy nobody.
    """
    m = re.compile(rf"<({tag})\b([^>]*?)(/?)>").match(xml, at)
    if not m:
        return xml, None
    real_tag, attrs, selfclose = m.group(1), m.group(2), m.group(3)
    # The element's full extent, so we can see (and edit) any children it already has. The
    # closing tag is matched against the document's own spelling, never the pattern.
    if selfclose:
        body, end = "", m.end()
    else:
        close = re.compile(rf"</{re.escape(real_tag)}>").search(xml, m.end())
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
    return (xml[:m.start()] + f"<{real_tag}{stripped}>{new_body}</{real_tag}>"
            + xml[end:]), before


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
    # part → [(locator, fragment, alt)]; alt is None for a decorative marking, which writes no text
    by_part: dict[str, list[tuple[str, str, str | None]]] = {}
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
        for locator, fragment, alt in targets:
            # Resolved against the CURRENT xml, once per write: an earlier write to this same
            # part has already shifted every offset after it.
            at = resolve_target(xml, tag, fragment)
            if at is None:
                unresolved.append(locator)                  # element gone: report, never guess
                continue
            if alt is None:
                xml, before = _set_decorative_in_xml(xml, tag, at)
            else:
                xml, before = _set_descr_in_xml(xml, tag, at, alt)
            if before is None:
                unresolved.append(locator)
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
