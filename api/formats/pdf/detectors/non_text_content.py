"""1.1.1 Non-text Content — PDF tagged figures.

Scope, stated plainly: this walks /StructTreeRoot for /Figure struct elements and reports the
ones carrying no usable /Alt. It says nothing about whether an /Alt that IS present actually
describes its image — that is a judgement, which is why 1.1.1 sits in the 🟡 review lane on
every format (remediation_capability.CAPABILITY) and why a clean result here is never a
certified pass.

WHY THIS EXISTS, when `pdf.missing-alt-text` already covers the pair in the partner catalog:
the write-back lane credits a reviewer's approved alt text by re-scanning the WRITTEN bytes and
finding 1.1.1 gone (handlers._apply_one_value_kind). `pdf.missing-alt-text` is a partner-engine
rule, so the in-process re-scan — proposals.verify_residual_scs, which runs first-party checks
only — could not observe 1.1.1 on a PDF at all. The criterion was absent from every re-scan
there would ever be, so the gate passed vacuously: the value was written, 1.1.1 was "cleared"
on no evidence, and the file certified against a criterion nothing had checked. That is the
exact failure tests/test_applier_detector_parity.py exists to prevent, reached through the one
door it does not close — a catalog rule the verifier cannot reach.

An untagged PDF yields nothing here on purpose: it has no tagged figures to judge, and its
missing tag tree is a separate structural finding. See formats.pdf.structure.
"""
from __future__ import annotations

from pathlib import Path

from formats.pdf import structure


def detect(path: Path) -> list[dict]:
    """One 1.1.1 finding per tagged /Figure with no usable /Alt."""
    try:
        import pikepdf
    except Exception:
        return []
    findings: list[dict] = []
    try:
        with pikepdf.open(str(path)) as pdf:
            for fig in structure.undescribed_figures(pdf):
                page = structure.page_number(fig, pdf)
                where = f" on page {page}" if page else ""
                findings.append({
                    "ruleId": "PDF_FIGURE_NO_ALT",
                    "wcag": "1.1.1 Non-text Content",
                    "severity": "CRITICAL",
                    "detail": (f"a tagged figure{where} has no alt text (/Alt) — a screen "
                               "reader announces nothing for it"),
                })
    except Exception:
        return []
    return findings
