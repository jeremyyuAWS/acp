"""2.5.3 Label in Name — PDF.

Scope: AcroForm push buttons. Push buttons are the only field type in PDF where both
the visible text label and the accessible name are programmatically available in the same
field object:

  Visible caption  → /MK /CA  (normal caption text, rendered on the button face)
  Accessible name  → /TU      (tooltip, preferred) or /T (partial name, fallback)

WCAG 2.5.3 requires the accessible name to CONTAIN the visible text (case-insensitive).
A push button whose /TU reads "Search the form" while its caption reads "Go" passes;
one whose /TU reads "btn_primary" while its caption reads "Submit" fails.

Coverage PARTIAL (not FULL): only push buttons carry a caption in the AcroForm dictionary.
Text fields, checkboxes, and radio buttons display labels as separate text objects on the
page — not linked to the field object — so they cannot be compared without rendering.
Confidence HIGH: within the push-button subset the comparison is exact and deterministic.

Rule ID: PDF_LABEL_NOT_IN_NAME
"""
from __future__ import annotations

from pathlib import Path

from formats.pdf import acroform
from swallowed import swallowed

# PDF Ff bit positions (0-indexed).  See ISO 32000 Table 227.
_FLAG_PUSHBUTTON = 1 << 16   # bit 17 in 1-indexed PDF spec notation
_FLAG_RADIO      = 1 << 15   # bit 16 — distinguishes radio from checkbox


def _is_pushbutton(field) -> bool:
    try:
        ff = int(field.get("/Ff") or 0)
        return bool(ff & _FLAG_PUSHBUTTON)
    except Exception:
        return False


def _caption(field) -> str | None:
    """Return the /MK /CA caption string, or None if absent/blank."""
    try:
        mk = field.get("/MK")
        if mk is None:
            return None
        ca = mk.get("/CA")
        if ca is None:
            return None
        text = str(ca).strip()
        return text if text else None
    except Exception:
        return None


def _accessible_name(field) -> str:
    """/TU if present and non-blank, else /T, else empty string."""
    try:
        tu = field.get("/TU")
        if tu is not None:
            text = str(tu).strip()
            if text:
                return text
    except Exception:
        swallowed("formats.pdf.detectors.label_in_name._accessible_name: reading the field's "
                  "accessible name failed")
    try:
        t = field.get("/T")
        return str(t).strip() if t is not None else ""
    except Exception:
        return ""


def detect(path: Path) -> list[dict]:
    """2.5.3 Label in Name — push buttons whose accessible name does not contain the caption."""
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

            failures: list[str] = []
            for field in fields:
                if str(field.get("/FT", "")) != "/Btn":
                    continue
                if not _is_pushbutton(field):
                    continue
                cap = _caption(field)
                if not cap:
                    continue          # no visible caption — nothing to compare
                name = _accessible_name(field)
                if cap.lower() not in name.lower():
                    failures.append(f'caption "{cap}" not in name "{name}"')

            if not failures:
                return []

            sample = "; ".join(failures[:3])
            if len(failures) > 3:
                sample += f" (and {len(failures) - 3} more)"
            return [{
                "ruleId": "PDF_LABEL_NOT_IN_NAME",
                "wcag": "2.5.3 Label in Name",
                "severity": "SERIOUS",
                "detail": (
                    f"push button accessible name does not contain the visible caption: {sample} — "
                    "speech-input users who activate the button by its visible label will fail"
                ),
            }]
    except Exception:
        return []
