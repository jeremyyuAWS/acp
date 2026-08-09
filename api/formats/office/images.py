"""Which images in an Office package still need alt text — the one predicate, shared.

The 1.1.1 DETECTOR and the 1.1.1 REMEDIATOR must agree on this exactly, for the same reason
the PDF pair must (see formats/pdf/structure.py). The write-back lane credits a reviewer's
approved alt text by re-scanning the WRITTEN bytes and finding 1.1.1 gone
(handlers._apply_one_value_kind), so a disagreement fails silently in one of two directions:

  - detector sees an image the remediator/applier does not -> the criterion never clears,
    every approval is written and then refused credit, and the file can never certify;
  - remediator sees one the detector does not -> the criterion clears while that image is
    still undescribed, and the file certifies with it.

So the target table and both predicates live here, and remediate_office imports them rather
than keeping its own copies. tests/test_office_alt_parity.py pins the two views equal on real
documents.

Locators are minted in the same `part#name` form apply_alt.parse_locator resolves, so a finding
here addresses exactly the element the approved text will be written to.
"""
from __future__ import annotations

import re

# (part pattern, alt-bearing tag, wrapper the tag must sit inside, derives-captions).
#
# The wrapper matters: pptx and xlsx put cNvPr on EVERY shape, and only pictures need alt.
# xlsx drawings come in two namespace flavours — Excel authors the prefixed `<xdr:pic>`, while
# openpyxl-family generators emit the same parts in the default namespace — so both are matched.
ALT_TARGETS = [
    (re.compile(r"^word/(document|header\d*|footer\d*)\.xml$"), "wp:docPr", None, True),
    (re.compile(r"^ppt/slides/slide\d+\.xml$"), "p:cNvPr", "p:pic", False),
    (re.compile(r"^xl/drawings/drawing\d+\.xml$"), r"(?:xdr:)?cNvPr", r"(?:xdr:)?pic", False),
]

_JUNK_DESCR = re.compile(
    r"^\s*(?:img|image|picture|photo|graphic|grafik)?[\s_-]*\d*\s*"
    r"(?:\.(?:png|jpe?g|gif|bmp|svg|tiff?|emf|wmf))?\s*$", re.I)
# a file path or arbitrary image filename ("icons/user.png", "media\image1.png", "logo.svg") —
# meaningless to a screen reader. A real description is a phrase (has spaces); these are single
# whitespace-free tokens, so only a space-free value is treated as filename-ish (which keeps
# "input/output diagram" descriptive).
_IMG_FILENAME = re.compile(r"^[^\s/\\]+\.(?:png|jpe?g|gif|bmp|svg|tiff?|emf|wmf)$", re.I)

_ATTR = lambda attrs, name: (re.search(rf'\b{name}="([^"]*)"', attrs) or [None, ""])[1]  # noqa: E731


def is_junk_descr(descr: str) -> bool:
    """True when descr is empty, a generic auto-name, or a file name/path rather than a real
    description — mirrors the .NET AltTextRule (WCAG 1.1.1)."""
    if _JUNK_DESCR.match(descr):
        return True
    trimmed = descr.strip()
    if not trimmed or any(c.isspace() for c in trimmed):
        return False
    if "/" in trimmed or "\\" in trimmed:
        return True
    return bool(_IMG_FILENAME.match(trimmed))


# Tolerant of anything between the element name and `val` — which in practice means a namespace
# declaration. See is_decorative for why that is not a hypothetical.
_DECORATIVE_MARKER = re.compile(r"decorative[^>]*\bval=[\"'](?:1|true)[\"']")


def is_decorative(block: str) -> bool:
    """True when the element carries the explicit decorative marker in its extLst children.

    A decorative image is CONFORMING with no alt text (WCAG 1.1.1 permits it), so flagging one
    would be a false positive — and, worse, the remediator already skips it, so the criterion
    could never be cleared on a document containing one.

    THAT IS NOT HYPOTHETICAL, AND IT IS WHY THIS IS A REGEX RATHER THAN A SUBSTRING TEST. This
    matched the literal text `decorative val="1"`, and the marker ACP ITSELF writes is

        <adec:decorative xmlns:adec="…/2017/decorative" val="1"/>

    with the namespace declared inline, because apply_alt._DECORATIVE_MARK is inserted as a
    standalone fragment and has nowhere else to declare it. The xmlns sits BETWEEN the two
    tokens, so the substring never matched and this returned False on ACP's own output. The
    remediator's own predicate (apply_alt._HAS_MARKER) is a regex and matched correctly, so it
    skipped the image — producing exactly the second failure this docstring warns about: mark an
    image decorative, re-scan, and 1.1.1 is still reported, forever, on a conforming document.

    Word escapes it by declaring xmlns:adec on the document root and emitting a bare
    `<adec:decorative val="1"/>`, which is why the bug survived: it is invisible on
    Word-authored files and only appears on files ACP has already remediated.

    The two predicates are now the same expression. tests/test_office_alt_parity.py pins them.
    """
    return bool(_DECORATIVE_MARKER.search(block))


def _element_block(xml: str, tag: str, m: re.Match) -> str:
    """The element's source span, used only to look for the decorative marker inside it.

    `tag` may be a regex alternation (`(?:xdr:)?cNvPr`), so the closing tag is matched with a
    regex rather than a literal find.
    """
    if m.group(2):                       # self-closing: no children, so no marker
        return m.group(0)
    close = re.compile(rf"</{tag}>").search(xml, m.end())
    return xml[m.start():close.start()] if close else m.group(0)


def undescribed_in_part(xml: str, tag: str, wrapper: str | None) -> list[str]:
    """Names of the alt-bearing elements in one part that still need a description."""
    spans = None
    if wrapper:
        spans = [mm.span() for mm in re.finditer(rf"<{wrapper}[ >].*?</{wrapper}>", xml, re.S)]
    out = []
    for m in re.finditer(rf"<{tag}\b([^>]*?)(/?)>", xml):
        if spans is not None and not any(a <= m.start() < b for a, b in spans):
            continue
        attrs = m.group(1)
        if not is_junk_descr(_ATTR(attrs, "descr")):
            continue
        if is_decorative(_element_block(xml, tag, m)):
            continue
        name = _ATTR(attrs, "name").strip()
        if name:                          # an unnamed element has no addressable locator
            out.append(name)
    return out


def undescribed_images(entries: dict[str, bytes]) -> list[dict]:
    """[{locator, part, name}] for every image in the package still needing alt text.

    `entries` is {part name: bytes}, the shape remediate_office already reads a package into.
    Parts that are not valid UTF-8 are skipped rather than failing the whole walk.
    """
    found: list[dict] = []
    for part in sorted(entries):
        for pat, tag, wrapper, _captions in ALT_TARGETS:
            if not pat.match(part):
                continue
            try:
                xml = entries[part].decode("utf-8")
            except (UnicodeDecodeError, AttributeError):
                continue
            for name in undescribed_in_part(xml, tag, wrapper):
                found.append({"locator": f"{part}#{name}", "part": part, "name": name})
    return found


def package_images(path) -> list[dict]:
    """[{locator, part, name}] for every image in the package at `path` still needing alt text.

    The zip read plus `undescribed_images`, which is the whole of the walk each format's 1.1.1
    detector shares. The FINDING is built per format, not here: the rules index reads a rule id
    and criterion from literals in the detector module itself, so a shared constructor would
    erase all three formats from the index (and from every parity check built on it). Sharing
    the question is right; sharing the declaration is not.
    """
    import zipfile
    try:
        with zipfile.ZipFile(path) as z:
            return undescribed_images({n: z.read(n) for n in z.namelist()})
    except Exception:
        return []                 # not a readable package — a separate, louder failure
