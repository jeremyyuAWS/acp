"""1.1.1 Non-text Content — xlsx images.

Reports every image in the package carrying no usable `descr` and not marked decorative. It
says nothing about whether a `descr` that IS present actually describes its image — that is a
judgement, which is why 1.1.1 sits in the 🟡 review lane on every format and why a clean result
here is never a certified pass.

WHY THIS EXISTS, when XLSX-ALT-001 already covers the pair in the partner catalog: the write-back
lane credits a reviewer's approved alt text by re-scanning the WRITTEN bytes and finding 1.1.1
gone (handlers._apply_one_value_kind). That is a partner-engine rule, so the in-process re-scan
— proposals.verify_residual_scs, which runs first-party checks only — could not observe 1.1.1
on an Office file at all. The criterion was absent from every re-scan there would ever be, so
the gate passed vacuously: the value was written, 1.1.1 was "cleared" on no evidence, and the
file certified against a criterion nothing had checked.

Demonstrated before this landed: demo-fixtures/powerpoint-accessibility-demo.pptx carries six
shapes with no `descr`, and a residual re-scan of it reported no 1.1.1 at all.

RULE_FORMATS has always listed xlsx for 1.1.1 — the pass/fail lane was declared, and only the
first-party implementation was missing. This fills it in; it is not a new claim.

The walk is shared with the remediator (formats/office/images.py) because detector and fixer
must judge the same images or the credit gate breaks silently in one of two directions. The
finding below is NOT shared: the rules index reads the rule id and criterion from this module,
so declaring them here is what puts xlsx 1.1.1 in the index at all.
"""
from __future__ import annotations

from pathlib import Path

from formats.office import images


def detect(path: Path) -> list[dict]:
    """One 1.1.1 finding per xlsx image with no usable alt text."""
    return [{
        "ruleId": "XLSX_IMAGE_NO_ALT",
        "wcag": "1.1.1 Non-text Content",
        "severity": "CRITICAL",
        "detail": f"image \u201c{img['name']}\u201d has no alt text \u2014 a screen reader announces nothing for it",
        "locator": img["locator"],
    } for img in images.package_images(path)]
