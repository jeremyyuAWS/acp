"""3.1.2 Language of Parts — xlsx.

Reports foreign-language passages that carry no language mark. The judgement is
`textchecks.detect_language_parts`, reused verbatim so this detector and the scan pipeline
(scanner.py, which calls `textchecks.content_findings`) can never disagree about what 3.1.2
fires on.

WHY coverage is PARTIAL, and why a clean scan is REVIEW not PASS. Two boundaries the technique
does not cross:

  * A passage must reach `textchecks._MIN_SEG_WORDS` (12) words in a language other than the
    document's own before langdetect is trusted to call it — a shorter foreign phrase or a single
    borrowed word is under the floor and unflagged.
  * "Which language a passage IS" is a statistical detection: langdetect can be wrong, and this
    detector supplies no `marked` dict (SpreadsheetML's rich-text run properties have no
    per-run language element, so there is nowhere in the format to record a mark — per
    office_structure.language_marked_spans, xlsx is absent by construction, not by omission).

No write-back can ever clear this finding: there is no element to write a language mark into.
The remediation lane is therefore human-only, and a clean result means "no unmarked foreign
passage long enough for us to be sure" — a real, useful check over a strict subset.
"""
from __future__ import annotations

from pathlib import Path


def detect(path: Path) -> list[dict]:
    """3.1.2 findings for an xlsx, reusing the exact logic the scan runs.

    Self-gating like every detector here: a missing part, an unreadable zip or a text-extraction
    failure yields [] rather than raising. A detector must never fail a scan.
    """
    try:
        import pii
        import textchecks

        text = pii.extract_text(path)
        if not text:
            return []
        return textchecks.detect_language_parts(text)
    except Exception:
        return []
