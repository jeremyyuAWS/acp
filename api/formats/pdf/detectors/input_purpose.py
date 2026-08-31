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
    # "Date of Birth" is the commonest English phrasing of this field and did NOT match,
    # while "Birth Date", "Birthdate", "Birth Day" and "DOB" all did — a false NEGATIVE
    # inside a detector whose documented weakness is false positives.
    r"|(date|day)[\s_.\-]?of[\s_.\-]?birth"
    r"|(^|[\s_.\-/])dob([\s_.\-/]|$)"
    r"|(^|[\s_.\-/])ssn([\s_.\-/]|$)"
    r"|credit[\s_.\-]?card"
    r"|(^|[\s_.\-/])cc[\s_.\-]?(num|number)([\s_.\-/]|$)",
    re.I,
)


# ── whose data is it? ────────────────────────────────────────────────────────────
#
# WCAG 1.3.5 covers "input fields COLLECTING INFORMATION ABOUT THE USER". A field collecting a
# company's address, or a third party's phone number, is outside it — the autocomplete vocabulary
# has no term for either — so a finding on one is a false positive, not a strict reading.
#
# The vocabulary above cannot tell whose data a field collects; that is the whole of its
# precision problem, and it is not a matter of the word list being too broad. Measured over a
# constructed set of 49 form labels (tests/test_input_purpose_precision.py): 15 of 20
# organisational or third-party labels were reported, against 0 of 12 ordinary business fields.
# Adding this context takes that from 15 false positives to 2, and precision from 52% to 89% ON
# THAT SET.
#
# WHAT IS DELIBERATELY NOT HERE, because each would trade a false positive for a worse false
# negative:
#   * bare "office" — "Office Phone" is the USER'S work phone, which 1.3.5 does cover.
#   * "customer" / "client" — on a form the customer fills in, "Customer Name" IS the user.
#   * "guardian" — on a child's form the guardian is often the person completing it.
#
# AND ITS OWN FALSE NEGATIVE, recorded rather than discovered later: on a sole-trader form "your
# company address" IS the user's own address, and this suppresses it. That is the cost of the
# trade, it is not hypothetical, and it is why this remains a HEURISTIC.
_NOT_THE_USER = re.compile(
    r"(^|[\s_.\-/])(company|employer|business|corporate|firm)([\s_.\-/]|$)"
    r"|organi[sz]ation"
    r"|(^|[\s_.\-/])(billing|invoice|vendor|supplier|contractor)([\s_.\-/]|$)"
    r"|(^|[\s_.\-/])(branch|warehouse|premises|depot|department|division)([\s_.\-/]|$)"
    r"|(^|[\s_.\-/])site([\s_.\-/]|$)"
    r"|(head|registered)[\s_.\-]?office"
    r"|(^|[\s_.\-/])(manager|supervisor|referee)([\s_.\-/]|$)"
    r"|emergency[\s_.\-]?contact"
    r"|next[\s_.\-]?of[\s_.\-]?kin",
    re.I,
)


def _collects_user_data(label: str) -> bool:
    """Does this field collect the USER'S OWN data, which is what WCAG 1.3.5 is about?"""
    return bool(_PERSONAL.search(label)) and not _NOT_THE_USER.search(label)


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
                if label and _collects_user_data(label):
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
