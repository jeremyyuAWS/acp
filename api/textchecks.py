"""Content checks on a document's extracted text — deterministic and reproducible
(no LLM: a compliance/audit tool must return the same findings for the same file
every run). Both detect-and-route: a finding is flagged automatically and sent to
human review, never auto-passed.

  1.3.3 Sensory Characteristics — instructions that rely on shape or visual
        location alone ("click the round button", "see the box on the right").
  3.1.2 Language of Parts — a document that mixes languages, where each passage's
        language should be marked. Detection is deterministic (langdetect seeded);
        self-gates to [] when langdetect isn't installed.

Both run on pii.extract_text output, so they cover every format the scanner reads
(HTML, PDF, docx/pptx/xlsx). Never raise — content checks must not fail a scan.
"""
from __future__ import annotations

import re

# ── 1.3.3 Sensory Characteristics ───────────────────────────────────────────────
# An instruction verb followed (within a short window, same sentence) by a
# shape-only or visual-location-only reference. Size/colour alone are noisier and
# overlap other SCs, so we anchor on the two strongest sensory-only signals:
# shape and position. Tight enough to avoid most prose; HITL confirms the rest.
_VERB = r"click|select|press|tap|choose|see|refer to|go to|use the|find the"
_SHAPE = r"round|circular|square|rectangular|triangular|oval|diamond-shaped"
_LOCATION = (r"(to|on|at|in) the (far )?(left|right|top|bottom|upper|lower)"
             r"|(top|bottom)[- ](left|right)|(left|right)[- ]hand|on the (left|right)"
             r"|(above|below|to the side)\b")
_SENSORY_RE = re.compile(
    rf"\b({_VERB})\b[^.!?\n]{{0,45}}\b(({_SHAPE})|{_LOCATION})", re.I)


def detect_sensory(text: str) -> list[dict]:
    if not text:
        return []
    if _SENSORY_RE.search(text):
        # One finding per document — the reviewer inspects the specific phrasing.
        return [{"ruleId": "SENSORY_INSTRUCTION", "wcag": "1.3.3 Sensory Characteristics",
                 "severity": "SERIOUS"}]
    return []


# ── 3.1.2 Language of Parts ─────────────────────────────────────────────────────
_MIN_SEG_WORDS = 12    # langdetect is unreliable below this; the conf guard covers the rest
_MIN_CONF = 0.90       # only count a confident detection
_MAX_SEGS = 200        # bound the work on huge documents
# Segment on sentence boundaries AND line breaks — extracted OOXML/PDF text has
# no reliable blank-line paragraphs, so splitting on those alone would collapse a
# whole document into one chunk and miss the language mix.
_SEG_SPLIT = re.compile(r"[.!?。！？\r\n]+")


def _langdetect_available() -> bool:
    try:
        from langdetect import DetectorFactory
        DetectorFactory.seed = 0  # deterministic — same text -> same result every run
        return True
    except Exception:
        return False


def detect_language_parts(text: str) -> list[dict]:
    if not text or not _langdetect_available():
        return []
    from langdetect import detect_langs
    segs = [s.strip() for s in _SEG_SPLIT.split(text) if len(s.split()) >= _MIN_SEG_WORDS]
    if len(segs) < 2:
        return []
    counts: dict[str, int] = {}
    for s in segs[:_MAX_SEGS]:
        try:
            res = detect_langs(s)
        except Exception:
            continue
        if res and res[0].prob >= _MIN_CONF:
            counts[res[0].lang] = counts.get(res[0].lang, 0) + 1
    # Two+ languages, each backed by at least one confident passage -> the
    # document mixes languages and each part's language should be marked.
    if len([lang for lang, n in counts.items() if n >= 1]) >= 2:
        return [{"ruleId": "LANG_PARTS_UNMARKED", "wcag": "3.1.2 Language of Parts",
                 "severity": "MODERATE"}]
    return []


def content_findings(text: str) -> list[dict]:
    """All text-content findings for one document (1.3.3 + 3.1.2)."""
    out: list[dict] = []
    try:
        out += detect_sensory(text)
    except Exception:
        pass
    try:
        out += detect_language_parts(text)
    except Exception:
        pass
    return out
