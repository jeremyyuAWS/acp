"""What a document format can physically tell us — the layer between WCAG and a detector.

A success criterion is a statement about a *document*. A detector is code against a *file
format*. Those two things fail to line up in a specific, recurring way: 4.1.2 Name/Role/Value
is one criterion, but establishing it means ARIA and the DOM in HTML, AcroForm widget
dictionaries and the tag tree in PDF, and exported accessibility metadata in Office. Written
as one "4.1.2 detector" that becomes a switch statement that grows a branch per format and
per parser improvement.

This module names the middle term. A format advertises the CAPABILITIES it exposes; a rule
declares which capabilities it REQUIRES. Whether a (rule, format) pair is assessable at all
then follows from set containment rather than from a hand-maintained table — and when it is
not assessable, the reason is a fact about the format ("PDF without a tag tree cannot express
programmatic role"), not a shrug.

The payoff is that new technology arrives as a capability, not as a rewrite. When a better
PDF parser can walk /StructTreeRoot reliably, the PDF adapter starts advertising TAG_TREE and
every rule requiring it becomes assessable — no engine change, no rule change.

Capabilities are per-DOCUMENT, not per-format-in-the-abstract. A scanned PDF and a tagged PDF
are the same file extension and almost nothing alike: one has OCR and pixels, the other has a
semantic tree. `capabilities_for()` inspects the actual file, which is why a rule can honestly
report "unsupported for THIS document" rather than "unsupported for PDF".
"""
from __future__ import annotations

from enum import Enum
from pathlib import Path


class Capability(str, Enum):
    """A thing a document can be interrogated for. Deliberately about the SUBSTRATE, not about
    accessibility: `TAG_TREE` is "this file carries a semantic structure tree", not "this file
    is accessible". Accessibility is what the rules conclude; capabilities are what they get
    to look at.

    str-valued so these serialise straight into the coverage JSON the WCAG matrix consumes.
    """

    TEXT = "text"                    # extractable text runs
    OCR = "ocr"                      # rasterised content an OCR pass can read
    STRUCTURE = "structure"          # headings / lists / sections as declared markup
    TAG_TREE = "tag_tree"            # a semantic tree with roles (PDF /StructTreeRoot, DOM)
    LINKS = "links"                  # hyperlinks with resolvable targets
    TABLES = "tables"                # tabular structure with header semantics
    FORMS = "forms"                  # interactive fields with names/types/values
    ANNOTATIONS = "annotations"      # PDF annots / comments layers
    METADATA = "metadata"            # document properties: title, language, author
    COLOR = "color"                  # resolvable foreground/background colour pairs
    FONTS = "fonts"                  # font family, size, weight, styling
    READING_ORDER = "reading_order"  # a declared linear order distinct from visual position
    DOM = "dom"                      # a live element tree with computed relationships
    ARIA = "aria"                    # explicit role/name/state annotations
    CSS = "css"                      # computed presentation, incl. responsive behaviour
    IMAGES = "images"                # embedded pictures/drawings carrying alt-text metadata


# Baseline per format — what the CURRENT parsers reliably reach for a typical document of
# that type. Deliberately conservative: advertising a capability the parser only sometimes
# delivers is how a rule ends up claiming coverage it doesn't have, which is the exact class
# of drift this whole layer exists to stop. `capabilities_for()` narrows or widens per file.
#
# TAG_TREE is absent from `pdf` on purpose. pikepdf can read /StructTreeRoot, but nothing in
# this codebase walks it to establish role/name/value — the 2.4.3 and 4.1.2 PDF detectors both
# stop at AcroForm widget dictionaries. Listing TAG_TREE here would make those rules look fully
# supported. It gets added when a detector actually walks the tree, and the rules requiring it
# become assessable on the same day, without touching them.
BASELINE: dict[str, frozenset[Capability]] = {
    "pdf": frozenset({
        Capability.TEXT, Capability.LINKS, Capability.FORMS, Capability.ANNOTATIONS,
        Capability.METADATA, Capability.COLOR, Capability.FONTS,
    }),
    # FORMS added when docx 4.1.2 was migrated to the registry. Word documents do carry
    # interactive fields — content controls (w:sdt with a checkbox/date/dropDown/comboBox/
    # picture gallery), whose Title is read straight from w:sdtPr — so the capability was
    # always present and simply undeclared. It is listed for docx and NOT for pptx/xlsx
    # because only Word has that construct; a spreadsheet's form controls are a different
    # object nothing here reads.
    #
    # Same discipline as TAG_TREE's absence from pdf, noted above: a capability appears here
    # when something in this codebase actually reads it, never to make a rule look supported.
    # IMAGES added when docx 1.1.1 was migrated to the registry. Word documents carry embedded
    # pictures/drawings whose alt text (wp:docPr @descr / a decorative marker) ACP reads through
    # formats/office/images.py — the capability was always present and simply undeclared, exactly
    # as FORMS was before 4.1.2's migration. It is listed for docx alone for now because only
    # docx 1.1.1 has been migrated; pptx/xlsx/pdf/html read images too (the same walk, plus their
    # own paths) and gain IMAGES here on the day their 1.1.1 moves to the registry — never sooner,
    # so the declaration tracks a real detector rather than an intention.
    "docx": frozenset({
        Capability.TEXT, Capability.STRUCTURE, Capability.LINKS, Capability.TABLES,
        Capability.METADATA, Capability.COLOR, Capability.FONTS, Capability.READING_ORDER,
        Capability.FORMS, Capability.IMAGES,
    }),
    "pptx": frozenset({
        Capability.TEXT, Capability.STRUCTURE, Capability.LINKS, Capability.TABLES,
        Capability.METADATA, Capability.COLOR, Capability.FONTS, Capability.READING_ORDER,
    }),
    "xlsx": frozenset({
        Capability.TEXT, Capability.STRUCTURE, Capability.LINKS, Capability.TABLES,
        Capability.METADATA, Capability.COLOR, Capability.FONTS,
    }),
    "html": frozenset({
        Capability.TEXT, Capability.STRUCTURE, Capability.LINKS, Capability.TABLES,
        Capability.FORMS, Capability.METADATA, Capability.COLOR, Capability.FONTS,
        Capability.READING_ORDER, Capability.DOM, Capability.ARIA, Capability.CSS,
        Capability.TAG_TREE,
    }),
}

FORMATS: tuple[str, ...] = ("docx", "xlsx", "pptx", "pdf", "html")


def capabilities_for(fmt: str, path: Path | None = None) -> frozenset[Capability]:
    """What THIS document exposes. Falls back to the format baseline when there is no file to
    inspect (the matrix's static grid asks this way — it reasons about formats, not documents).

    Per-document inspection is the point: a scanned PDF is a picture of a document. It has no
    text, no forms, no structure — only pixels. A rule requiring FORMS must be able to say
    "this document cannot answer that" rather than silently passing or silently failing.
    """
    base = BASELINE.get(fmt, frozenset())
    if path is None:
        return base
    adapt = _ADAPTERS.get(fmt)
    if adapt is None:
        return base
    try:
        return adapt(path, base)
    except Exception:
        # An adapter that can't read the file must not break a scan. The baseline is the
        # honest fallback: it is what we'd have claimed with no inspection at all.
        return base


def _pdf_adapter(path: Path, base: frozenset[Capability]) -> frozenset[Capability]:
    """Narrow the PDF baseline to what this file actually carries.

    Two adjustments matter. A file with no /AcroForm has no FORMS to interrogate, so the
    form-backed rules report unsupported-for-this-document instead of a vacuous pass. And a
    scanned page — effectively no extractable text, one big image — trades TEXT for OCR, which
    is the honest description of what any downstream check has to work with.
    """
    import pikepdf

    caps = set(base)
    with pikepdf.open(str(path)) as pdf:
        root = pdf.Root
        acroform = root.get("/AcroForm") if "/AcroForm" in root else None
        if not (acroform is not None and "/Fields" in acroform and len(acroform["/Fields"])):
            caps.discard(Capability.FORMS)
        if "/StructTreeRoot" in root:
            # The tree EXISTS in this file. That is a fact about the document and belongs here;
            # whether any detector walks it is a fact about our code and belongs in the
            # registry's coverage. Keeping the two separate is what lets a future tag-tree
            # detector light up its rules without touching this adapter.
            caps.add(Capability.TAG_TREE)
            caps.add(Capability.STRUCTURE)

    if _looks_scanned(path):
        # A scanned page is a picture of a document: the substrate genuinely changes. Saying so
        # lets a text-backed rule report "this document has no extractable text" instead of
        # passing vacuously on a file where it read nothing at all.
        caps.discard(Capability.TEXT)
        caps.discard(Capability.FONTS)
        caps.add(Capability.OCR)
    return frozenset(caps)


_SCAN_PROBE_PAGES = 3      # enough to classify; a capability probe must stay cheap
_SCAN_MAX_CHARS = 5        # mirrors office_structure._SCANNED_MAX_CHARS


def _looks_scanned(path: Path) -> bool:
    """Near-zero extractable text across the first few pages.

    Same floor as `office_structure.pdf_scanned_page_checks` so the capability layer and the
    1.4.5 detector can never disagree about whether a file is scanned — two heuristics with
    different thresholds would eventually classify the same document both ways.
    """
    try:
        import pdfplumber
        with pdfplumber.open(str(path)) as pdf:
            pages = pdf.pages[:_SCAN_PROBE_PAGES]
            if not pages:
                return False
            return all(len(p.chars) <= _SCAN_MAX_CHARS for p in pages)
    except Exception:
        return False       # can't tell -> don't claim it; the baseline stands


# Per-format capability adapters. A format with no entry simply uses its baseline — adding a
# new format is a BASELINE entry, and an adapter only when per-document narrowing matters.
_ADAPTERS: dict[str, object] = {"pdf": _pdf_adapter}


def missing(required: frozenset[Capability] | set[Capability],
            available: frozenset[Capability]) -> list[Capability]:
    """Which required capabilities this document doesn't offer. Sorted so a reason string is
    stable across runs — these end up in user-visible copy and in test assertions."""
    return sorted(set(required) - set(available), key=lambda c: c.value)


def describe(caps: list[Capability]) -> str:
    """Capabilities as prose for an end-user 'why not' message."""
    names = {
        Capability.TAG_TREE: "a semantic tag tree",
        Capability.FORMS: "interactive form fields",
        Capability.ARIA: "explicit role annotations",
        Capability.DOM: "a live element tree",
        Capability.READING_ORDER: "a declared reading order",
        Capability.OCR: "readable page images",
        Capability.TEXT: "extractable text",
        Capability.CSS: "computed presentation",
    }
    parts = [names.get(c, c.value.replace("_", " ")) for c in caps]
    if len(parts) <= 1:
        return parts[0] if parts else ""
    return ", ".join(parts[:-1]) + " and " + parts[-1]
