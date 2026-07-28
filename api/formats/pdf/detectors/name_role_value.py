"""4.1.2 Name, Role, Value — PDF.

Scope, stated plainly because the registry's `coverage=PARTIAL` depends on it: this walks
AcroForm terminal field dictionaries and nothing else. For each field it establishes the three
halves of the criterion from the field dictionary —

    Name  -> /TU  (the accessible name AT announces)
    Role  -> /FT  (one of the four spec-defined field types)
    Value -> /V or /DV, and only for fields flagged required

— which is sound for interactive forms and says nothing at all about the other population
4.1.2 covers on a PDF: components expressed through the tagged-structure tree. Establishing
role/name/value there means walking /StructTreeRoot, which nothing in this codebase does yet.

That is why the registration requires only `Capability.FORMS` and not `TAG_TREE`, and why a
clean result is REVIEW rather than PASS: we genuinely checked every form field, and genuinely
did not check anything else. When a tag-tree detector lands, this pair's coverage moves to FULL
and clean scans start certifying — with no change to this file or to the engine.

Behaviour is unchanged from `office_structure.pdf_form_field_checks`, which this replaces.
"""
from __future__ import annotations

from pathlib import Path

from formats.pdf import acroform


def detect(path: Path) -> list[dict]:
    """4.1.2 findings per interactive form field: no accessible name (/TU), no recognized role
    (/FT), or — for a required field — no determinable value (/V)."""
    try:
        import pikepdf
    except Exception:
        return []
    findings: list[dict] = []
    try:
        with pikepdf.open(str(path)) as pdf:
            root = pdf.Root
            if not acroform.has_fields(root):
                return []
            fields: list = []
            for f in root["/AcroForm"]["/Fields"]:
                acroform.terminal_fields(f, fields, set())
            for fld in fields:
                name = ""
                try:
                    name = str(fld.get("/T", "")).strip()
                except Exception:
                    name = ""
                label = f"“{name}”" if name else "an interactive form field"
                if acroform.field_unnamed(fld):
                    findings.append({
                        "ruleId": "PDF_FORM_NO_ACCESSIBLE_NAME",
                        "wcag": "4.1.2 Name, Role, Value",
                        "severity": "CRITICAL",
                        "detail": f"form field {label} has no accessible name (/TU)" if name
                                  else f"{label} has no accessible name (/TU)",
                    })
                if acroform.field_bad_type(fld):
                    findings.append({
                        "ruleId": "PDF_FORM_NO_FIELD_TYPE",
                        "wcag": "4.1.2 Name, Role, Value",
                        "severity": "CRITICAL",
                        "detail": f"form field {label} has no recognized /FT — its role (button, "
                                  "text box, choice, signature) isn't determinable",
                    })
                if acroform.field_required_no_value(fld):
                    findings.append({
                        "ruleId": "PDF_FORM_REQUIRED_NO_VALUE",
                        "wcag": "4.1.2 Name, Role, Value",
                        "severity": "SERIOUS",
                        "detail": f"required form field {label} has no value (/V) and no "
                                  "default (/DV) — its current state isn't determinable",
                    })
    except Exception:
        return []
    return findings
