"""Server-side PDF remediation (ADR 0005 step 4).

Applies the two DETERMINISTIC PDF fixers from the vendored DigitalA11y engine —
document language (`/Lang`) and display-document-title (ViewerPreferences) — which
are pure pikepdf, no LLM and no extra dependencies. The LLM-driven PDF fixers
(real title text, alt-text, bookmark structure) need content judgement and are
intentionally NOT run here: they route to human review, the same 'deferred'
contract the HTML remediator uses (api/remediate.py).

This invokes the fixers directly rather than the full RemediationEngine, so it
pulls in only pikepdf + the two clean fixer modules — not the engine's optional
LLM client / pypdfium / BeautifulSoup dependencies.
"""
from __future__ import annotations
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace


def remediate_pdf(path: Path, *, lang: str = "en"):
    """Apply deterministic PDF accessibility fixes to a copy of the file.

    Returns (fixed_path, applied, skipped):
      fixed_path — Path to the remediated PDF, or None if nothing was applied.
      applied/skipped — human-readable change descriptions.
    """
    from scanner import WP  # vendored worker-python root (engine + fixers)
    sys.path.insert(0, str(WP))
    import pikepdf
    from remediation.fixers.pdf.language_fixer import PdfLanguageFixer
    from remediation.fixers.pdf.display_title_fixer import PdfDisplayTitleFixer
    from remediation.base_fixer import FixBehavior, FixStatus

    try:
        pdf = pikepdf.open(str(path))
    except Exception as e:
        return None, [], [f"could not open PDF: {type(e).__name__}"]

    behavior = FixBehavior(allow_llm=False, allow_placeholders=True)
    applied: list[str] = []
    skipped: list[str] = []
    try:
        for fixer, meta in ((PdfLanguageFixer(), {"language": lang}),
                            (PdfDisplayTitleFixer(), {})):
            # The deterministic fixers read only issue.issue_id, so a light stub
            # avoids constructing a full A11yIssue (and its enum imports).
            issue = SimpleNamespace(issue_id=uuid.uuid4())
            res = fixer.apply(pdf, issue, meta, behavior)
            (applied if res.status == FixStatus.FIXED else skipped).append(res.description)
        if applied:
            # Provenance stamp in the document Info dictionary — who/what/when/standard.
            from datetime import datetime, timezone
            from remediate_office import TOOL, VERSION
            stamp = {
                "/Producer": f"{TOOL} {VERSION}",
                "/RemediatedBy": TOOL,
                "/RemediationDate": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                "/WCAGTarget": "WCAG 2.1 AA",
                "/FixesApplied": "; ".join(applied)[:255],
            }
            for k, v in stamp.items():
                pdf.docinfo[pikepdf.Name(k)] = v
        out_path = path.with_name(f"remediated-{path.name}")
        pdf.save(str(out_path))
    finally:
        pdf.close()
    return (out_path if applied else None), applied, skipped
