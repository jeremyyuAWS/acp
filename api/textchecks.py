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


_SENSORY_MAX = 10   # per-document cap — bounds work and review noise on pathological docs


def _sentence_around(text: str, start: int, end: int) -> str:
    """The (whitespace-normalised, capped) sentence containing text[start:end] — the
    evidence a reviewer needs to find the instruction without re-reading the document."""
    left = max(text.rfind(".", 0, start), text.rfind("\n", 0, start),
               text.rfind("!", 0, start), text.rfind("?", 0, start)) + 1
    rights = [i for i in (text.find(c, end) for c in ".!?\n") if i != -1]
    right = min(rights) + 1 if rights else len(text)
    return re.sub(r"\s+", " ", text[left:right]).strip()[:200]


def detect_sensory(text: str) -> list[dict]:
    """One finding PER sensory-only instruction, each carrying the offending sentence as
    `detail` — the reviewer sees exactly which phrasing fired instead of a bare rule id
    they must hunt for in the document. Deduped by sentence, capped at _SENSORY_MAX."""
    if not text:
        return []
    out: list[dict] = []
    seen: set[str] = set()
    for m in _SENSORY_RE.finditer(text):
        sentence = _sentence_around(text, m.start(), m.end())
        if not sentence or sentence in seen:
            continue
        seen.add(sentence)
        out.append({"ruleId": "SENSORY_INSTRUCTION", "wcag": "1.3.3 Sensory Characteristics",
                    "severity": "SERIOUS",
                    "detail": f"instruction relies on shape/position alone: “{sentence}”"})
        if len(out) >= _SENSORY_MAX:
            break
    return out


# ── 3.1.2 Language of Parts ─────────────────────────────────────────────────────
_MIN_SEG_WORDS = 12    # langdetect is unreliable below this; the conf guard covers the rest
_MIN_CONF = 0.90       # only count a confident detection
_MAX_SEGS = 200        # bound the work on huge documents
# Segment on sentence boundaries AND line breaks — extracted OOXML/PDF text has
# no reliable blank-line paragraphs, so splitting on those alone would collapse a
# whole document into one chunk and miss the language mix.
_SEG_SPLIT = re.compile(r"[.!?。！？\r\n]+")


_CODE_CHARS = set("{};=<>#*_|\\")


def _looks_like_code(seg: str) -> bool:
    """CSS/markup/code that leaks into extracted text (e.g. an HTML file's inline <style>)
    is confidently mislabelled by langdetect ('h1 { margin: 0 }' → Romanian, live false
    positive on careers-landing.html). Human prose contains none of these characters and is
    letter-dominant; code fails one of the two."""
    if any(c in _CODE_CHARS for c in seg):
        return True
    letters = sum(c.isalpha() or c.isspace() for c in seg)
    return letters / max(len(seg), 1) < 0.75


def _langdetect_available() -> bool:
    try:
        from langdetect import DetectorFactory
        DetectorFactory.seed = 0  # deterministic — same text -> same result every run
        return True
    except Exception:
        return False


def _is_marked(seg: str, lang: str, marked: dict[str, str]) -> bool:
    """True when `seg` is already marked as `lang` in the document's own markup.

    `marked` is {base language subtag: text carrying that mark} from
    office_structure.language_marked_spans. The passage must be marked as the language it
    WAS DETECTED AS — a run stamped with the document's default en-US does not satisfy 3.1.2
    for a French passage, and PowerPoint stamps that default on nearly every run, so matching
    on "has any mark" would silently retire this detector.

    Whether the marked code is the linguistically CORRECT one is a content question 3.1.2
    does not ask — the same reading the capability registry already records for 3.1.1 html.
    """
    pool = marked.get((lang or "").split("-")[0].strip().lower(), "")
    if not pool:
        return False
    needle = " ".join(seg.split())
    return bool(needle) and " ".join(pool.split()).find(needle[:80]) != -1


def detect_language_parts(text: str, marked: dict[str, str] | None = None) -> list[dict]:
    """Foreign passages whose language the document never identifies (WCAG 3.1.2).

    `marked` (optional) is the document's own language marks, so a passage that IS marked
    stops counting. Omitted, the check behaves exactly as before — every caller that cannot
    supply markup (plain text, PDF, xlsx) keeps its previous behaviour.
    """
    marked = marked or {}
    if not text or not _langdetect_available():
        return []
    import html as _html
    # Office extractors can leave HTML entities raw ('r&#233;gions' for 'régions') — decode
    # so accents reach langdetect and entity punctuation doesn't read as code.
    text = _html.unescape(text)
    from langdetect import detect_langs
    segs = [s.strip() for s in _SEG_SPLIT.split(text)
            if len(s.split()) >= _MIN_SEG_WORDS and not _looks_like_code(s)]
    if len(segs) < 2:
        return []
    # Every confident passage, with whether the document identifies it as what it IS.
    # The primary language is counted over ALL of them, marked or not: it is the document's
    # own baseline, and dropping marked passages first would erase it. Word and PowerPoint
    # stamp the default language on nearly every run, so a document whose English is marked
    # en-US and whose French is marked not at all would have looked single-language and
    # passed — retiring this detector on exactly the files it exists to catch.
    counts: dict[str, int] = {}
    seen: list[tuple[str, str]] = []          # (segment, detected language)
    for s in segs[:_MAX_SEGS]:
        try:
            res = detect_langs(s)
        except Exception:
            continue
        if res and res[0].prob >= _MIN_CONF:
            counts[res[0].lang] = counts.get(res[0].lang, 0) + 1
            seen.append((s, res[0].lang))
    if len(counts) < 2:
        return []
    primary = max(counts, key=lambda k: counts[k])
    # 3.1.2 is about the PARTS: a passage in a language other than the document's own, whose
    # language the document never identifies. A passage already marked as the language it was
    # detected as satisfies the criterion and must stop keeping the finding alive — counting
    # it anyway is what made this check unclearable by any write.
    unmarked: dict[str, int] = {}
    for s, lang in seen:
        if lang == primary or _is_marked(s, lang, marked):
            continue
        unmarked[lang] = unmarked.get(lang, 0) + 1
    if unmarked:
        mix = ", ".join(f"{lang} ({n} passage{'s' if n != 1 else ''})"
                        for lang, n in sorted(unmarked.items(), key=lambda kv: -kv[1]))
        return [{"ruleId": "LANG_PARTS_UNMARKED", "wcag": "3.1.2 Language of Parts",
                 "severity": "MODERATE",
                 "detail": f"document is mainly {primary} but has unmarked passages in "
                           f"another language: {mix}"}]
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
# Sentence boundaries: terminal punctuation AND line breaks. Extracted PDF/OOXML
# text (bulleted lists, tables, forms, title pages) is often punctuation-free but
# line-broken; without treating newlines as boundaries the whole document collapses
# into one "sentence", the words/sentence ratio explodes, and FK grade blows past
# the threshold on trivially readable content (a real false-positive found in review).
_SENT_SPLIT = re.compile(r"[.!?\r\n]+")
_VOWEL_GROUP = re.compile(r"[aeiouy]+")
# Even after splitting on newlines, a blob with neither punctuation nor line breaks
# yields one enormous "sentence" — that's unpunctuated extraction, not dense prose,
# so the grade is unreliable and we decline to score rather than false-flag.
_MAX_WORDS_PER_SENTENCE = 80


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
    n_words = len(words)
    if n_words / n_sent > _MAX_WORDS_PER_SENTENCE:
        return None  # unpunctuated / not well-formed prose — don't guess a grade
    syllables = sum(_syllables(w) for w in words)
    return 0.39 * (n_words / n_sent) + 11.8 * (syllables / n_words) - 15.59


def detect_reading_level(text: str) -> list[dict]:
    if not text:
        return []
    grade = flesch_kincaid_grade(text)
    if grade is not None and grade >= _MIN_GRADE:
        return [{"ruleId": "READING_LEVEL_ADVANCED", "wcag": "3.1.5 Reading Level",
                 "severity": "MODERATE",
                 "detail": f"document reads at Flesch-Kincaid grade {grade:.1f} "
                           f"(flagged at ≥ {_MIN_GRADE:.0f}; the SC targets ~grade 9)"}]
    return []


def content_findings(text: str, marked: dict[str, str] | None = None) -> list[dict]:
    """All text-content findings for one document (1.3.3 + 3.1.2 + 3.1.5).

    `marked` is the document's own language marks (office_structure.language_marked_spans),
    so 3.1.2 can tell a marked passage from an unmarked one. Optional: a caller with only
    text — and every format with no per-run language mechanism — gets the previous behaviour.
    """
    out: list[dict] = []
    try:
        out += detect_sensory(text)
    except Exception:
        pass
    try:
        out += detect_language_parts(text, marked)
    except Exception:
        pass
    try:
        out += detect_reading_level(text)
    except Exception:
        pass
    return out
