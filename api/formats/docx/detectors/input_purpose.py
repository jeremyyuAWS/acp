"""1.3.5 Identify Input Purpose — DOCX.

Heuristic: reads interactive content controls (date, dropdown, comboBox, checkbox) and flags
any whose w:alias (Title) matches the WCAG personal-data vocabulary. OOXML content controls
carry no autocomplete attribute, so any personal-data field is a structural gap the format
cannot close.

Coverage is HEURISTIC: the vocabulary match is approximate. Organisational forms whose
controls happen to be titled "address" or "name" will false-positive. Confidence is LOW.
A clean scan resolves to REVIEW, not PASS.
"""
from __future__ import annotations

import zipfile
from pathlib import Path

from office_structure import _SDT, _SDT_ALIAS, _SDT_INPUT_TYPE, _SDT_PR, _docx_story_xmls

_PERSONAL_DATA = frozenset({
    "name", "first", "last", "given", "family", "surname", "middle", "nickname",
    "email", "e-mail",
    "phone", "tel", "telephone", "mobile", "cell", "fax",
    "address", "street", "city", "town", "state", "province", "zip", "postal", "country",
    "birth", "birthday", "dob",
    "sex", "gender",
    "password", "passwd",
    "username",
    "ssn", "social security",
    "credit", "card",
    "organization", "company",
})


def _matches(text: str) -> bool:
    t = text.lower()
    return any(term in t for term in _PERSONAL_DATA)


def detect(path: Path) -> list[dict]:
    """1.3.5 findings for DOCX content controls whose Title (w:alias) matches personal-data vocabulary.

    Never raises — a detector must not fail a scan.
    """
    findings: list[dict] = []
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
                    alias = alias_m.group(1).strip()
                    if not _matches(alias):
                        continue
                    findings.append({
                        "ruleId": "DOCX_INPUT_NO_PURPOSE",
                        "wcag": "1.3.5 Identify Input Purpose",
                        "severity": "MODERATE",
                        "detail": (
                            f"content control \"{alias}\" appears to collect personal user data "
                            "but OOXML has no programmatic purpose declaration "
                            "(no autocomplete attribute)"
                        ),
                    })
    except (zipfile.BadZipFile, OSError):
        return []
    return findings
