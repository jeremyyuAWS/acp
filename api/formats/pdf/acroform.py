"""AcroForm field primitives, shared by the PDF detectors that reason about interactive fields.

Moved verbatim from `office_structure.py` when 4.1.2 and 2.4.3 were migrated to the registry.
They live here rather than beside one detector because both criteria interrogate the same
structure from different angles — 4.1.2 asks what a field IS, 2.4.3 asks what order fields come
in — and a helper owned by one detector but imported by another is how a format module starts
turning back into a shared grab-bag.
"""
from __future__ import annotations


def terminal_fields(node, out, seen) -> None:
    """Recursively collect terminal AcroForm fields (those with /FT), following /Kids."""
    try:
        import pikepdf
    except Exception:
        return
    if not isinstance(node, pikepdf.Dictionary):
        return
    oid = id(node)
    if oid in seen:
        return
    seen.add(oid)
    kids = node.get("/Kids")
    if "/FT" in node and not (isinstance(kids, pikepdf.Array) and len(kids)
                              and any("/FT" in k for k in kids if isinstance(k, pikepdf.Dictionary))):
        out.append(node)          # a terminal field (its kids, if any, are widgets, not fields)
    if isinstance(kids, pikepdf.Array):
        for k in kids:
            terminal_fields(k, out, seen)


def field_unnamed(field) -> bool:
    try:
        tu = field.get("/TU")
        return tu is None or not str(tu).strip()
    except Exception:
        return False


# The four field types the PDF spec (1.7 §12.7.3.1) defines — /FT is guaranteed present on
# every node terminal_fields collects (that's its own inclusion test), but its VALUE is
# never validated by the collector. A value outside this set has no determinable role:
# assistive tech can't tell whether it's a text box, checkbox, radio button, or signature.
VALID_FIELD_TYPES = {"/Btn", "/Tx", "/Ch", "/Sig"}


def field_bad_type(field) -> bool:
    try:
        ft = field.get("/FT")
        return ft is None or str(ft) not in VALID_FIELD_TYPES
    except Exception:
        return False


def field_required_no_value(field) -> bool:
    """A REQUIRED field (Ff bit 2 — PDF 1.7 Table 221) with no /V and no fallback /DV has no
    determinable value — the "Value" half of 4.1.2, distinct from /TU's "Name" half. A field
    that isn't required is fine empty (a blank optional text box is not a finding)."""
    try:
        ff = field.get("/Ff")
        if ff is None or not (int(ff) & 2):
            return False
        has_value = "/V" in field and str(field.get("/V", "")).strip()
        has_default = "/DV" in field and str(field.get("/DV", "")).strip()
        return not (has_value or has_default)
    except Exception:
        return False


def page_has_widget(page, pikepdf) -> bool:
    try:
        annots = page.obj.get("/Annots")
        return bool(annots) and any(
            str(a.get("/Subtype", "")) == "/Widget" for a in annots if isinstance(a, pikepdf.Dictionary))
    except Exception:
        return False


def has_fields(root) -> bool:
    """True when the document carries a non-empty AcroForm field tree.

    Mirrors the FORMS capability test in `capabilities._pdf_adapter`. Both exist because they
    answer for different callers — the adapter for "can this rule run at all", this for "is
    there anything to walk" — but they must agree, so they test the same three things.
    """
    if "/AcroForm" not in root:
        return False
    acro = root["/AcroForm"]
    return "/Fields" in acro and bool(len(acro["/Fields"]))
