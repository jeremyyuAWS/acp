"""2.4.4 Link Purpose (In Context) — PDF.

Reports link annotations whose visible text is the raw URL: the URI of a /Link's /URI action
appears verbatim in the page text. A bare URL is not a meaningful link label.

WHY coverage is PARTIAL, and why a clean scan is REVIEW not PASS. The technique checks one
specific failure pattern — a link whose URI string appears literally as its visible text in the
extracted page content. It does not check whether otherwise-descriptive text names the
destination, or whether generic filler phrases ("click here", "learn more") are used, which the
docx detector also covers. So a clean result means "no link whose URL appears verbatim in page
text", a real check over a strict subset — which is what PARTIAL coverage and the REVIEW lane
encode (ADR 0016 / 0031).

This is a MECHANISM migration only: the pair moves from the legacy `store.RULE_FORMATS` +
`_certify` path to the capability registry's coverage gate, and the per-file verdict is unchanged
(raw-URL link found → FAIL, clean scan → REVIEW instead of the overclaiming PASS the old path
returned).
"""
from __future__ import annotations

from pathlib import Path


def detect(path: Path) -> list[dict]:
    """2.4.4 findings for a PDF. Never raises — a detector must not fail a scan."""
    from office_structure import pdf_link_purpose_check
    return pdf_link_purpose_check(path)
