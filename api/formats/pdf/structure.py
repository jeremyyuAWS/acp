"""Tagged-PDF structure-tree reads shared by the 1.1.1 detector and the 1.1.1 remediator.

One traversal, used by both sides, on purpose. The write-back lane credits a fix by re-scanning
the written bytes and finding the criterion gone (handlers._apply_one_value_kind), so the
detector's idea of "a figure that needs alt text" and the fixer's idea of "a figure to write
/Alt on" must be the SAME SET. Two near-copies of this walk would drift into one of two silent
failures, and neither announces itself:

  - detector sees figures the fixer misses -> the criterion never clears, every approval is
    written and then refused credit, and the file can never certify;
  - fixer sees figures the detector misses -> the criterion clears without those figures being
    described, and the file certifies with undescribed images in it.

tests/test_pdf_figure_parity.py pins the two views equal on the same document.
"""
from __future__ import annotations


def collect_figures(node, figures: list | None = None) -> list:
    """Every /Figure struct element reachable from `node` (normally /StructTreeRoot).

    Mirrors the pdf.missing-alt-text analyser's traversal, so the elements we judge are the
    elements it judges. Never raises: a malformed sub-tree contributes nothing rather than
    failing the whole walk.
    """
    import pikepdf
    if figures is None:
        figures = []
    try:
        if isinstance(node, pikepdf.Dictionary):
            if str(node.get("/S", "")) == "/Figure":
                figures.append(node)
            for key in ("/K", "/C"):
                if key in node:
                    child = node[key]
                    if isinstance(child, pikepdf.Array):
                        for item in child:
                            collect_figures(item, figures)
                    else:
                        collect_figures(child, figures)
        elif isinstance(node, pikepdf.Array):
            for item in node:
                collect_figures(item, figures)
    except Exception:
        pass
    return figures


def figure_alt(figure) -> str | None:
    """A figure's /Alt, or None when it is absent or whitespace-only.

    Whitespace-only counts as absent on BOTH sides deliberately: a figure carrying `/Alt ( )`
    is not described, and treating it as described would let a document certify on a space.
    """
    try:
        raw = figure.get("/Alt")
        if raw is None:
            return None
        val = str(raw).strip()
        return val or None
    except Exception:
        return None


def undescribed_figures(pdf) -> list:
    """The /Figure elements in an open pikepdf document that carry no usable /Alt.

    Empty for an untagged PDF — a document with no /StructTreeRoot has no tagged figures to
    judge, and its missing tag tree is a separate structural finding (pdf.tagged), not a
    1.1.1 one. Reporting 1.1.1 there too would double-count one defect as two.
    """
    try:
        root = pdf.Root
        if "/StructTreeRoot" not in root:
            return []
        return [f for f in collect_figures(root["/StructTreeRoot"]) if figure_alt(f) is None]
    except Exception:
        return []


def page_number(figure, pdf) -> int | None:
    """1-based page number for a figure via its /Pg reference, or None when unresolvable."""
    try:
        pg_ref = figure.get("/Pg")
        if pg_ref is None:
            return None
        for i, page in enumerate(pdf.pages):
            if page.obj.objgen == pg_ref.objgen:
                return i + 1
    except Exception:
        pass
    return None
