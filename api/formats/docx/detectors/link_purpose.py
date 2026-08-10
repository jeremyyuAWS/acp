"""2.4.4 Link Purpose (In Context) — docx.

Reports hyperlinks whose display text names nothing about where they go ("click here", a bare
URL). The judgement — `office_structure._vague_link_findings` over `_docx_hyperlinks` (body plus
the running header/footer and foot/endnote parts, #214) — is reused verbatim, so this detector
and the scan's own link check (office_structure.docx_checks) fire on exactly the same links.

WHY coverage is PARTIAL, and why a clean scan is REVIEW not PASS. The technique judges whether
link text is a GENERIC filler phrase or a raw URL — checkable structurally. It does not judge
whether otherwise-fine text describes THIS destination: a link reading "Annual Report" that
points at last year's is a 2.4.4 failure this check passes, because accuracy-to-target is a
content judgement no read of the XML settles (ADR 0031, Group A). So a clean result means "no
link with obviously contentless text", a real check over a strict subset — which is what PARTIAL
coverage and the REVIEW lane encode.

This is a MECHANISM migration only: the pair moves from the legacy `store.RULE_FORMATS` +
`_certify` path to the capability registry's coverage gate, and the per-file verdict is unchanged
(clean → REVIEW, a vague link → FAIL).
"""
from __future__ import annotations

import zipfile
from pathlib import Path


def detect(path: Path) -> list[dict]:
    """2.4.4 findings for a docx, from the same helpers the scan uses.

    Self-gating: a bad zip or missing document part yields [] rather than raising.
    """
    try:
        import office_structure as osx

        with zipfile.ZipFile(path) as zf:
            doc = osx._read(zf, "word/document.xml")
            if not doc:
                return []
            links = osx._docx_hyperlinks(zf, doc)
        return osx._vague_link_findings(
            [t for t, _ in links], "DOCX_LINK_PURPOSE_VAGUE", "2.4.4 Link Purpose (In Context)")
    except (zipfile.BadZipFile, OSError):
        return []
