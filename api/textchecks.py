"""Content checks on a document's extracted text — deterministic and reproducible
(no LLM: a compliance/audit tool must return the same findings for the same file
every run). Both detect-and-route: a finding is flagged automatically and sent to
human review, never auto-passed.

  1.3.3 Sensory Characteristics — instructions that rely on shape or visual
        location alone ("click the round button", "see the box on the right").
  3.1.2 Language of Parts — a document that mixes languages, where each passage's
        language should be marked. Detection is deterministic (langdetect seeded);
        self-gates to [] when langdetect isn't installed.
  3.1.5 Reading Level — text whose Flesch-Kincaid grade level is far above the
        "lower secondary" bar the SC targets, i.e. genuinely dense prose that
        warrants a plain-language alternative. Pure arithmetic on the text, no
        deps, fully reproducible.

All run on pii.extract_text output, so they cover every format the scanner reads
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


# ── 3.1.5 Reading Level ─────────────────────────────────────────────────────────
# Flesch-Kincaid Grade Level = 0.39·(words/sentences) + 11.8·(syllables/words) − 15.59.
# The SC's bar is "lower secondary education level" (~grade 9), but flagging every
# document above grade 9 would fire on essentially all professional prose and be
# useless noise. We deliberately only flag text that is genuinely dense — grade
# _MIN_GRADE and up (early-college and beyond) — where a plain-language summary is
# a real, defensible ask; the milder grade-9..N band is left to the reviewer.
_MIN_WORDS_FOR_READING = 200   # a readability score on a short snippet is meaningless
_MIN_GRADE = 15.0              # ~ mid-college; well above the SC's grade-9 floor
_WORD_RE = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?")
_SENT_SPLIT = re.compile(r"[.!?]+")
_VOWEL_GROUP = re.compile(r"[aeiouy]+")


def _syllables(word: str) -> int:
    """Heuristic syllable count: vowel groups, minus a silent trailing 'e',
    floored at 1. Standard readability-tool approximation — not perfect on every
    word, but the aggregate over hundreds of words is stable and reproducible."""
    w = word.lower()
    groups = len(_VOWEL_GROUP.findall(w))
    if w.endswith("e") and not w.endswith("le") and groups > 1:
        groups -= 1
    return max(1, groups)


def flesch_kincaid_grade(text: str) -> float | None:
    """FK grade level, or None if there isn't enough text to be meaningful."""
    words = _WORD_RE.findall(text)
    if len(words) < _MIN_WORDS_FOR_READING:
        return None
    sentences = [s for s in _SENT_SPLIT.split(text) if s.strip()]
    n_sent = max(1, len(sentences))
    syllables = sum(_syllables(w) for w in words)
    n_words = len(words)
    return 0.39 * (n_words / n_sent) + 11.8 * (syllables / n_words) - 15.59


def detect_reading_level(text: str) -> list[dict]:
    if not text:
        return []
    grade = flesch_kincaid_grade(text)
    if grade is not None and grade >= _MIN_GRADE:
        return [{"ruleId": "READING_LEVEL_ADVANCED", "wcag": "3.1.5 Reading Level",
                 "severity": "MODERATE"}]
    return []


def content_findings(text: str) -> list[dict]:
    """All text-content findings for one document (1.3.3 + 3.1.2 + 3.1.5)."""
    out: list[dict] = []
    try:
        out += detect_sensory(text)
    except Exception:
        pass
    try:
        out += detect_language_parts(text)
    except Exception:
        pass
    try:
        out += detect_reading_level(text)
    except Exception:
        pass
    return out
