"""3.1.2 Language of Parts — docx.

Reports foreign-language passages the document never identifies with a `w:lang` mark. The
judgement is `textchecks.detect_language_parts`, reused verbatim so this detector and the scan
pipeline (scanner.py, which calls `textchecks.content_findings`) can never disagree about what
3.1.2 fires on — the same discipline `name_role_value` follows by importing office_structure's
own regexes rather than re-deriving them.

WHY coverage is PARTIAL, and why a clean scan is REVIEW not PASS. Two boundaries the technique
does not cross, named so the registration's `reason` is honest:

  * A passage must reach `textchecks._MIN_SEG_WORDS` (12) words in a language other than the
    document's own before langdetect is trusted to call it — a shorter foreign phrase, a single
    borrowed word, is under the floor and unflagged.
  * "Which language a passage IS" is a detection, not a certainty: langdetect is a statistical
    model, and whether the marked BCP-47 code is the linguistically correct one is a content
    question no scan settles.

So a clean result means "no unmarked foreign passage long enough for us to be sure" — a real,
useful check over a strict subset, which is exactly what PARTIAL coverage and the REVIEW lane
encode (ADR 0016 / 0031). This is a MECHANISM migration only: the pair moves from the legacy
`store.RULE_FORMATS` + `_certify` path to the capability registry's coverage gate, and the
per-file verdict is unchanged (clean → REVIEW, an unmarked passage → FAIL).
"""
from __future__ import annotations

from pathlib import Path


def detect(path: Path) -> list[dict]:
    """3.1.2 findings for a docx, reusing the exact logic the scan runs.

    Self-gating like every detector here: a missing part, an unreadable zip or a text-extraction
    failure yields [] rather than raising. A detector must never fail a scan.
    """
    try:
        import pii
        import textchecks
        from office_structure import language_marked_spans

        text = pii.extract_text(path)
        if not text:
            return []
        marked = language_marked_spans(path, ".docx")
        return textchecks.detect_language_parts(text, marked)
    except Exception:
        return []
