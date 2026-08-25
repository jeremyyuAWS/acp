"""2.4.3 Focus Order — PDF.

Two complementary checks, run in order:

1.  StructTreeRoot vs AcroForm comparison (NEW — partial coverage):
    When the document carries both an AcroForm and a /StructTreeRoot, widget
    annotations are collected in two ordered lists:
      • AcroForm field-tree order  = the keyboard tab order when /Tabs /S is set
      • OBJR order in the structure tree = the document reading order
    Any inversion in the matched set is flagged: a field the user tabs to before
    another field that appears earlier visually is a focus-order failure even when
    /Tabs /S is set.

2.  /Tabs = /S page check (EXISTING — heuristic fallback):
    When no structure-tree comparison is possible (PDF not tagged, or no widget
    OBJRs in the tree), pages with form-field widgets that lack /Tabs = /S are
    flagged. This is a proxy — correlated with bad tab order but neither necessary
    nor sufficient for it.

Coverage upgrade: PARTIAL (was HEURISTIC). Within the matched set (widgets present
in both trees) the comparison is exact; outside it (non-widget elements, /R or /C
layouts, untagged PDFs) coverage is still heuristic via the /Tabs fallback.
"""
from __future__ import annotations

from pathlib import Path

from formats.pdf import acroform


# ── helpers ───────────────────────────────────────────────────────────────────

def _objnum(obj) -> int | None:
    """Return the PDF indirect-object number for a pikepdf Dictionary, or None."""
    try:
        return obj.objgen[0]
    except Exception:
        return None


def _acroform_widget_objnums(root, pikepdf) -> list[int]:
    """Walk the AcroForm field tree and return widget object numbers in tab order.

    A terminal field (has /FT) may be a merged field+widget (has /Subtype /Widget)
    or may have pure-widget /Kids. Both shapes are handled.
    """
    fields: list = []
    try:
        seen_fields: set[int] = set()
        for f in root["/AcroForm"]["/Fields"]:
            acroform.terminal_fields(f, fields, seen_fields)
    except Exception:
        return []
    result: list[int] = []
    seen: set[int] = set()
    for field in fields:
        if str(field.get("/Subtype", "")) == "/Widget":
            n = _objnum(field)
            if n is not None and n not in seen:
                seen.add(n)
                result.append(n)
        else:
            kids = field.get("/Kids")
            if isinstance(kids, pikepdf.Array):
                for k in kids:
                    if (isinstance(k, pikepdf.Dictionary)
                            and str(k.get("/Subtype", "")) == "/Widget"):
                        n = _objnum(k)
                        if n is not None and n not in seen:
                            seen.add(n)
                            result.append(n)
    return result


def _struct_objnums(node, out: list[int], seen: set[int], pikepdf) -> None:
    """Recursively walk a StructTreeRoot node, collecting OBJR /Obj object numbers."""
    try:
        if not isinstance(node, pikepdf.Dictionary):
            return
        node_id = id(node)
        if node_id in seen:
            return
        seen.add(node_id)
        if str(node.get("/Type", "")) == "/OBJR":
            obj = node.get("/Obj")
            if obj is not None:
                n = _objnum(obj)
                if n is not None:
                    out.append(n)
            return
        kids = node.get("/K")
        if kids is None:
            return
        if isinstance(kids, pikepdf.Array):
            for k in kids:
                if isinstance(k, pikepdf.Dictionary):
                    _struct_objnums(k, out, seen, pikepdf)
        elif isinstance(kids, pikepdf.Dictionary):
            _struct_objnums(kids, out, seen, pikepdf)
    except Exception:
        return


def _struct_widget_objnums(root, pikepdf) -> list[int]:
    """Return OBJR object numbers from the StructTreeRoot in document-structure order."""
    try:
        struct_root = root.get("/StructTreeRoot")
        if struct_root is None:
            return []
    except Exception:
        return []
    out: list[int] = []
    seen: set[int] = set()
    _struct_objnums(struct_root, out, seen, pikepdf)
    return out


def _has_inversion(acro_order: list[int], struct_order: list[int]) -> bool:
    """Return True if any pair of matched widgets is in a different relative order.

    Only widgets appearing in both lists are compared; widgets present in one list
    but not the other are ignored (partially-tagged forms are common). Requires
    >= 2 matched widgets to make any comparison.
    """
    common = {n for n in acro_order if n in set(struct_order)}
    if len(common) < 2:
        return False
    acro_seq = [n for n in acro_order if n in common]
    struct_seq = [n for n in struct_order if n in common]
    # Build rank maps: rank_X[objnum] = position in list X
    acro_rank = {n: i for i, n in enumerate(acro_seq)}
    struct_rank = {n: i for i, n in enumerate(struct_seq)}
    for i, a in enumerate(acro_seq):
        for b in acro_seq[i + 1:]:
            if (acro_rank[a] < acro_rank[b]) != (struct_rank[a] < struct_rank[b]):
                return True
    return False


# ── detector ─────────────────────────────────────────────────────────────────

def detect(path: Path) -> list[dict]:
    """2.4.3 Focus Order — prefer structure-tree comparison; fall back to /Tabs check."""
    try:
        import pikepdf
    except Exception:
        return []
    try:
        with pikepdf.open(str(path)) as pdf:
            root = pdf.Root
            if not acroform.has_fields(root):
                return []

            acro_order = _acroform_widget_objnums(root, pikepdf)
            struct_order = _struct_widget_objnums(root, pikepdf)

            # Primary: structure-tree comparison (exact within scope)
            if acro_order and struct_order:
                if _has_inversion(acro_order, struct_order):
                    return [{
                        "ruleId": "PDF_FOCUS_ORDER_STRUCT_MISMATCH",
                        "wcag": "2.4.3 Focus Order",
                        "severity": "MODERATE",
                        "detail": (
                            "the keyboard tab order of form fields (AcroForm field tree) "
                            "does not match their order in the document structure tree — "
                            "a screen reader user will encounter fields out of reading order"
                        ),
                    }]
                return []   # struct comparison ran and found no mismatch — clean

            # Fallback: /Tabs = /S heuristic for untagged or field-less struct trees
            bad_pages = 0
            for page in pdf.pages:
                if not acroform.page_has_widget(page, pikepdf):
                    continue
                tabs = page.obj.get("/Tabs")
                if tabs is None or str(tabs) != "/S":
                    bad_pages += 1
            if not bad_pages:
                return []
            return [{
                "ruleId": "PDF_TAB_ORDER_NOT_STRUCTURE",
                "wcag": "2.4.3 Focus Order",
                "severity": "MODERATE",
                "detail": (f"{bad_pages} page(s) with form fields have no /Tabs entry "
                           "set to /S (structure order) — the keyboard tab sequence may "
                           "not follow reading order"),
            }]
    except Exception:
        return []
