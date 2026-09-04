"""2.5.3 Label in Name — PDF.

Two checks, different confidence:

DETERMINISTIC — AcroForm push buttons (rule PDF_LABEL_NOT_IN_NAME, SERIOUS):
  Visible caption  → /MK /CA  (normal caption text, rendered on the button face)
  Accessible name  → /TU      (tooltip, preferred) or /T (partial name, fallback)
  WCAG 2.5.3 requires the accessible name to CONTAIN the visible text (case-insensitive).

HEURISTIC — all other field types: text (/Tx), checkbox/radio (/Btn non-pushbutton),
  choice (/Ch), signature (/Sig) (rule PDF_ACCESSIBLE_NAME_PROGRAMMATIC, MODERATE):
  These fields display their visible label as separate text objects on the page, not
  linked to the field object, so a direct caption-to-name comparison requires rendering.
  Instead, the accessible name is flagged when it looks like a developer identifier
  (snake_case containing underscores, or camelCase starting lowercase with an uppercase
  letter) — a programmatic name will never match what a speech-input user says.

Coverage PARTIAL (not FULL): push buttons carry both caption and name in the same dict;
other fields require a rendering step not available here.
"""
from __future__ import annotations

from pathlib import Path

from formats.pdf import acroform
from swallowed import swallowed

# PDF Ff bit positions (0-indexed).  See ISO 32000 Table 227.
_FLAG_PUSHBUTTON = 1 << 16   # bit 17 in 1-indexed PDF spec notation
_FLAG_RADIO      = 1 << 15   # bit 16 — distinguishes radio from checkbox

# AcroForm field types other than push buttons covered by the heuristic check.
_HEURISTIC_FTS = frozenset({"/Tx", "/Ch", "/Sig"})


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


def _looks_programmatic(name: str) -> bool:
    """True when name looks like a developer identifier rather than a human-readable label.

    Flags snake_case (contains underscore) and camelCase (starts lowercase with at least
    one uppercase letter). Single-word names starting uppercase ('Name', 'Email') and
    names with spaces ('Full Name') are not flagged — they read as plausible labels.
    """
    if not name or any(c.isspace() for c in name):
        return False
    if '_' in name:
        return True
    return name[0].islower() and any(c.isupper() for c in name)


def detect(path: Path) -> list[dict]:
    """2.5.3 Label in Name — push buttons (deterministic) and other fields (heuristic)."""
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

            pushbtn_failures: list[str] = []
            heuristic_failures: list[str] = []

            for field in fields:
                ft = str(field.get("/FT", ""))
                if ft == "/Btn" and _is_pushbutton(field):
                    cap = _caption(field)
                    if not cap:
                        continue
                    name = _accessible_name(field)
                    if cap.lower() not in name.lower():
                        pushbtn_failures.append(f'caption "{cap}" not in name "{name}"')
                elif ft in _HEURISTIC_FTS or (ft == "/Btn" and not _is_pushbutton(field)):
                    name = _accessible_name(field)
                    if _looks_programmatic(name):
                        field_id = str(field.get("/T") or "")
                        heuristic_failures.append(
                            f'field {field_id!r} has programmatic accessible name {name!r}'
                        )

            results: list[dict] = []

            if pushbtn_failures:
                sample = "; ".join(pushbtn_failures[:3])
                if len(pushbtn_failures) > 3:
                    sample += f" (and {len(pushbtn_failures) - 3} more)"
                results.append({
                    "ruleId": "PDF_LABEL_NOT_IN_NAME",
                    "wcag": "2.5.3 Label in Name",
                    "severity": "SERIOUS",
                    "detail": (
                        f"push button accessible name does not contain the visible caption: {sample} — "
                        "speech-input users who activate the button by its visible label will fail"
                    ),
                })

            if heuristic_failures:
                sample = "; ".join(heuristic_failures[:3])
                if len(heuristic_failures) > 3:
                    sample += f" (and {len(heuristic_failures) - 3} more)"
                results.append({
                    "ruleId": "PDF_ACCESSIBLE_NAME_PROGRAMMATIC",
                    "wcag": "2.5.3 Label in Name",
                    "severity": "MODERATE",
                    "detail": (
                        f"form field accessible name appears to be a developer identifier: {sample} — "
                        "speech-input users say the visible label; a programmatic name will not match"
                    ),
                })

            return results
    except Exception:
        return []
