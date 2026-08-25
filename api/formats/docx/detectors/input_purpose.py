"""1.3.5 Identify Input Purpose — DOCX.

OOXML content controls (`w:sdt`) carry `w:alias` (the Title / accessible name) and `w:tag`
(a developer identifier) but no autocomplete-equivalent attribute: the Word Open XML
specification defines no mechanism for a content control to declare its programmatic input
purpose in the sense WCAG 1.3.5 requires.

This detector identifies content controls of interactive types (checkbox, date, dropDownList,
comboBox) whose `w:alias` title matches the WCAG input-purpose vocabulary (name, email, phone,
address, birth date, etc.) and flags them: a document with such controls cannot satisfy 1.3.5.

The finding is advisory — a static heuristic based on field-name patterns, so some false
positives and false negatives are possible — hence HEURISTIC coverage and LOW confidence.

Rule ID: DOCX_INPUT_NO_PURPOSE
"""
from __future__ import annotations

import re
import zipfile
from pathlib import Path

from office_structure import _SDT, _SDT_ALIAS, _SDT_INPUT_TYPE, _SDT_PR, _docx_story_xmls

# Same personal-data vocabulary as the PDF counterpart and the HTML scanner.
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


def detect(path: Path) -> list[dict]:
    """1.3.5 Identify Input Purpose — flag personal-data content controls lacking purpose metadata.

    OOXML provides no autocomplete-equivalent mechanism, so any interactive content control
    whose w:alias title matches a personal-data pattern cannot programmatically declare its
    input purpose.
    """
    matched: list[str] = []
    try:
        with zipfile.ZipFile(path) as zf:
            for doc in _docx_story_xmls(zf):
                for sdt_inner in _SDT.findall(doc):
                    pr_m = _SDT_PR.search(sdt_inner)
                    if not pr_m or not _SDT_INPUT_TYPE.search(pr_m.group(1)):
                        continue
                    alias_m = _SDT_ALIAS.search(pr_m.group(1))
                    if not alias_m:
                        continue
                    label = alias_m.group(1).strip()
                    if label and _PERSONAL.search(label):
                        matched.append(label)
    except (zipfile.BadZipFile, OSError):
        return []

    if not matched:
        return []

    sample = ", ".join(f'"{s}"' for s in matched[:3])
    if len(matched) > 3:
        sample += f" (and {len(matched) - 3} more)"
    return [{
        "ruleId": "DOCX_INPUT_NO_PURPOSE",
        "wcag": "1.3.5 Identify Input Purpose",
        "severity": "MODERATE",
        "detail": (
            f"content control(s) appear to collect personal user information ({sample}) "
            "but OOXML provides no mechanism to declare input purpose programmatically — "
            "assistive technologies cannot automatically populate these fields; "
            "consider migrating personal-data forms to accessible HTML with autocomplete attributes"
        ),
    }]
