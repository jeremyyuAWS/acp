"""Write a reviewer-approved alt text into an Office document (WCAG 1.1.1).

The proposal lane (api/proposals.py) drafts alt text and stores it on the file's HITL row,
one proposal per image, each carrying a `locator` minted by remediate_office:

    locator = "<part name>#<cNvPr/docPr name>"      e.g. "ppt/slides/slide3.xml#Picture 4"

Approving those drafts used to store text and stop there: nothing wrote it into the document,
so the images stayed undescribed and store.mark_file_compliant_if_reviewed correctly refused
to certify the file — which left it stranded, approved but never conformant. This module is
the missing write: it resolves each locator back to its element and sets `descr`.

Deliberately narrow. It only sets a `descr` attribute on an element that already exists, it
never adds, removes, or reorders anything, and it rewrites only the parts it actually touched.
A locator it cannot resolve is REPORTED, never guessed at — a silently misapplied alt text is
worse than an unapplied one, because a reviewer signed their name to it.
"""
from __future__ import annotations
import io
import re
import zipfile

# Which element carries the alt text, per part. Mirrors remediate_office._ALT_TARGETS: the
# same table that minted the locators must resolve them, or a locator would address an
# element this module cannot find.
_ALT_TAG_FOR_PART = [
    (re.compile(r"^word/(document|header\d*|footer\d*)\.xml$"), "wp:docPr"),
    (re.compile(r"^ppt/slides/slide\d+\.xml$"), "p:cNvPr"),
    (re.compile(r"^xl/drawings/drawing\d+\.xml$"), "xdr:cNvPr"),
]

_ATTR = lambda attrs, name: (re.search(rf'\b{name}="([^"]*)"', attrs) or [None, ""])[1]


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
    for m in re.finditer(rf"<{re.escape(tag)}\b([^>]*?)(/?)>", xml):
        attrs, selfclose = m.group(1), m.group(2)
        if found is not None or _ATTR(attrs, "name").strip() != name:
            continue
        found = _ATTR(attrs, "descr")
        stripped = re.sub(r'\s*\bdescr="[^"]*"', "", attrs)   # drop any existing descr
        out.append(xml[last:m.start()])
        out.append(f'<{tag}{stripped} descr="{_xesc(alt)}"{selfclose}>')
        last = m.end()
    if found is None:
        return xml, None
    out.append(xml[last:])
    return "".join(out), found


def apply_alt_text(data: bytes, values: dict[str, str]) -> tuple[bytes, list[dict], list[str]]:
    """Write each locator's approved alt text into the Office package `data`.

    values: {locator: alt text}. Returns (new_bytes, applied, unresolved):
      applied    — [{locator, before, after}], one per element actually written, in the
                   caller's order, ready for store.record_remediation_diffs.
      unresolved — locators whose part or element was not found. The caller must surface
                   these rather than treating the approval as honoured.

    When nothing resolves, the ORIGINAL bytes are returned unchanged — never a rezipped
    copy that differs only by compression, which would look like a modified document.
    """
    values = {k: v for k, v in (values or {}).items() if v and v.strip()}
    if not values:
        return data, [], []

    with zipfile.ZipFile(io.BytesIO(data)) as zin:
        names = zin.namelist()
        entries = {n: zin.read(n) for n in names}

    # Group by part so each XML part is parsed and rewritten once, not once per image.
    by_part: dict[str, list[tuple[str, str, str]]] = {}     # part → [(locator, name, alt)]
    unresolved: list[str] = []
    for locator, alt in values.items():
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
            xml, before = _set_descr_in_xml(xml, tag, name, alt)
            if before is None:
                unresolved.append(locator)                  # element gone: report, never guess
                continue
            applied.append({"locator": locator,
                            "before": before or "(no alt text)",
                            "after": alt})
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
