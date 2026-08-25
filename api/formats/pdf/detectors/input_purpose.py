"""1.3.5 Identify Input Purpose — PDF.

Heuristic: walks AcroForm terminal fields and flags any whose /T (partial name) or /TU
(tooltip/accessible name) matches the WCAG personal-data vocabulary. PDF AcroForm has no
programmatic autocomplete attribute — there is no HTML-equivalent mechanism — so any
interactive field that appears to collect personal user data is a structural gap the format
cannot close.

Coverage is HEURISTIC: the vocabulary match is approximate. Organisational forms whose
fields happen to include "address" or "name" will false-positive; whether a field truly
collects user-specific personal data is a human judgement. Confidence is LOW for the
same reason. A clean scan (no vocabulary matches) resolves to REVIEW, not PASS.
"""
from __future__ import annotations

from pathlib import Path

from formats.pdf import acroform

# Personal-data terms drawn from the WCAG 1.3.5 HTML autocomplete token list.
# Matched as substrings of the lowercased field name / tooltip.
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
    """1.3.5 findings for PDF AcroForm fields whose /T or /TU matches personal-data vocabulary.

    Never raises — a detector must not fail a scan.
    """
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
                t_val = tu_val = ""
                try:
                    t_val = str(fld.get("/T", "")).strip()
                    tu_val = str(fld.get("/TU", "")).strip()
                except Exception:
                    pass
                if not (_matches(t_val) or _matches(tu_val)):
                    continue
                label = tu_val or t_val or "unnamed field"
                findings.append({
                    "ruleId": "PDF_INPUT_NO_PURPOSE",
                    "wcag": "1.3.5 Identify Input Purpose",
                    "severity": "MODERATE",
                    "detail": (
                        f"form field \"{label}\" appears to collect personal user data "
                        "but PDF AcroForm has no programmatic purpose declaration "
                        "(no HTML autocomplete equivalent)"
                    ),
                })
    except Exception:
        return []
    return findings
