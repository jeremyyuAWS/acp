"""1.3.5 Identify Input Purpose — PDF.

PDF AcroForm fields carry /T (partial field name) and /TU (tooltip / accessible name) but have
no autocomplete-equivalent attribute: the PDF specification (ISO 32000) defines no mechanism for
a form field to declare its programmatic input purpose in the sense WCAG 1.3.5 requires.

This detector identifies form fields whose /T or /TU value matches the WCAG input-purpose
vocabulary (name, email, phone, address, birth date, etc.) and flags them: a document with such
fields cannot satisfy 1.3.5 in PDF form. The finding is advisory — a static heuristic based on
field-name patterns, so some false positives and false negatives are possible — hence HEURISTIC
rather than PARTIAL coverage and LOW confidence.

Rule ID: PDF_INPUT_NO_PURPOSE
"""
from __future__ import annotations

import re
from pathlib import Path

from formats.pdf import acroform

# WCAG 1.3.5 § 7 Input Purposes for User Interface Components — personal-data vocabulary.
# Same root vocabulary as the HTML _INPUT_PURPOSE pattern in scanner.py, extended slightly
# for form-field naming conventions (CamelCase, underscores, dot-separated XFA paths).
_PERSONAL = re.compile(
    r"e-?mail"
    r"|(^|[\s_.\-/])(tel|phone|mobile|fax)([\s_.\-/]|$)"
    r"|(first|given)[\s_.\-]?name"
    r"|(last|family|sur)[\s_.\-]?name"
    r"|full[\s_.\-]?name"
    r"|(^|[\s_.\-/])(zip|postal)([\s_.\-]?code)?([\s_.\-/]|$)"
    r"|(^|[\s_.\-/])country([\s_.\-/]|$)"
    r"|(^|[\s_.\-/])(city|town)([\s_.\-/]|$)"
    r"|street|address"
    r"|birth[\s_.\-]?(date|day)"
    r"|(^|[\s_.\-/])dob([\s_.\-/]|$)"
    r"|(^|[\s_.\-/])ssn([\s_.\-/]|$)"
    r"|credit[\s_.\-]?card"
    r"|(^|[\s_.\-/])cc[\s_.\-]?(num|number)([\s_.\-/]|$)",
    re.I,
)


def _field_label(field) -> str:
    """Return the best available human-readable label for a terminal field."""
    tu = field.get("/TU")
    t = field.get("/T")
    parts = []
    if tu is not None:
        parts.append(str(tu))
    if t is not None:
        parts.append(str(t))
    return " ".join(parts)


def detect(path: Path) -> list[dict]:
    """1.3.5 Identify Input Purpose — flag personal-data AcroForm fields lacking purpose metadata.

    PDF provides no autocomplete-equivalent mechanism, so any field whose name/tooltip matches a
    personal-data pattern cannot programmatically declare its input purpose.
    """
    try:
        import pikepdf
    except Exception:
        return []
    try:
        with pikepdf.open(str(path)) as pdf:
            root = pdf.Root
            if not acroform.has_fields(root):
                return []

            fields: list = []
            seen_fields: set[int] = set()
            try:
                for f in root["/AcroForm"]["/Fields"]:
                    acroform.terminal_fields(f, fields, seen_fields)
            except Exception:
                return []

            matched: list[str] = []
            for field in fields:
                label = _field_label(field)
                if label and _PERSONAL.search(label):
                    matched.append(label)

            if not matched:
                return []

            sample = ", ".join(f'"{s}"' for s in matched[:3])
            if len(matched) > 3:
                sample += f" (and {len(matched) - 3} more)"
            return [{
                "ruleId": "PDF_INPUT_NO_PURPOSE",
                "wcag": "1.3.5 Identify Input Purpose",
                "severity": "MODERATE",
                "detail": (
                    f"form field(s) appear to collect personal user information ({sample}) "
                    "but PDF provides no mechanism to declare input purpose programmatically — "
                    "assistive technologies cannot automatically populate these fields; "
                    "consider migrating personal-data forms to accessible HTML with autocomplete attributes"
                ),
            }]
    except Exception:
        return []
