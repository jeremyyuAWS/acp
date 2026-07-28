"""2.4.3 Focus Order — PDF.

Scope, which is why the registry marks this `coverage=HEURISTIC` rather than PARTIAL: it
checks that a page carrying form-field widgets declares /Tabs = /S, and stops there. A missing
or non-/S /Tabs is a proxy for "the tab sequence probably doesn't follow reading order" — it
correlates well, but it is a signal about a page-level flag, not a comparison of two orders.

The distinction from 4.1.2's PARTIAL matters. 4.1.2's form technique is *sound over a subset*:
every AcroForm field it examines, it judges correctly. This one is *approximate over the whole*:
/Tabs = /S is neither necessary nor sufficient for correct focus order. /R (row order) and /C
(column order) are legitimate for some layouts, and a page can declare /S and still tab in a
nonsensical sequence. Proving the real thing means walking /StructTreeRoot and comparing it to
the widget order — a separate, larger gap that nothing here does yet.

Because it is heuristic, its findings are advisory (severity MODERATE, review-lane) and a clean
result is REVIEW, never a certified pass. Behaviour is unchanged from
`office_structure.pdf_focus_order_checks`, which this replaces.
"""
from __future__ import annotations

from pathlib import Path

from formats.pdf import acroform


def detect(path: Path) -> list[dict]:
    """2.4.3 Focus Order — a page carrying interactive form-field widgets whose /Tabs entry is
    missing or isn't /S (structure order). Pages with no widgets are untouched — nothing to tab
    through, so /Tabs is moot there."""
    try:
        import pikepdf
    except Exception:
        return []
    bad_pages = 0
    try:
        with pikepdf.open(str(path)) as pdf:
            root = pdf.Root
            if not acroform.has_fields(root):
                return []
            for page in pdf.pages:
                if not acroform.page_has_widget(page, pikepdf):
                    continue
                tabs = page.obj.get("/Tabs")
                if tabs is None or str(tabs) != "/S":
                    bad_pages += 1
    except Exception:
        return []
    if not bad_pages:
        return []
    return [{
        "ruleId": "PDF_TAB_ORDER_NOT_STRUCTURE",
        "wcag": "2.4.3 Focus Order",
        "severity": "MODERATE",
        "detail": (f"{bad_pages} page(s) with form fields have no /Tabs entry set to /S "
                   "(structure order) — the keyboard tab sequence may not follow reading order"),
    }]
