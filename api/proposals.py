"""Shared spine for the AI-proposes → validate → one-click-approve remediation lane.

The platform already had this pattern in exactly one place — vision alt text: a fix is
proposed, the fixed bytes are re-scanned (`verify_residual_scs`), and only a criterion that
verifiably clears is credited. This module generalises the pieces every remediator needs to
route a *proposal* — a concrete, pre-computed fix value a reviewer can approve in one click
instead of drafting from a blank — through the same honest gate:

  * A DETERMINISTIC derivation that clears the re-scan → auto-applied inline by the
    remediator (High confidence). The existing post-apply re-scan is the validator.
  * A local-MODEL value (vision alt, a rewrite) or a HEURISTIC inference (decorative) →
    surfaced as a one-click card (Medium / Low) and NEVER auto-applied — because a cleared
    re-scan proves the finding stopped firing, not that the value is correct. The analyser
    cannot tell good alt text from garbage, so a machine-authored value is always a proposal
    a human confirms, never a silent auto-fix.

No third-party AI: model-backed proposers call api/ai.py (local Ollama) only, so the
"no commercial LLM" claim holds. Nothing here raises on the remediation path — a proposer
that fails just yields no proposal and the finding falls back to human review.
"""
from __future__ import annotations

import posixpath
import re
from urllib.parse import unquote, urlparse

# ── Proposal shape ────────────────────────────────────────────────────────────
# A proposal is a plain dict (same posture as applied_fixes rows / remediate _rec diffs —
# no dataclass ceremony). One per finding instance; stored as the JSON array in
# hitl_queue.proposals (store.enqueue_proposals):
#   locator        — identifies the element the value applies to so the approve path can
#                    apply it back (an href, a run index, an image part+rid, a page number).
#   before         — the offending value/text, for the card's before→after and the cert PDF.
#   proposed_value — the concrete value to approve in one click.
#   rationale      — the "why" shown next to the value (evidence, not a score).
#   source         — human-readable provenance ("derived from the link target",
#                    "AI vision model (llava)"), which also encodes the honesty tier.
#   thumb          — optional base64 image thumbnail for image proposals.


def proposal(locator, before, proposed_value, rationale, source, thumb=None, kind=None) -> dict:
    p = {"locator": locator, "before": before, "proposed_value": proposed_value,
         "rationale": rationale, "source": source}
    if thumb:
        p["thumb"] = thumb
    if kind:
        p["kind"] = kind   # e.g. 'decorative' → the card offers "Mark decorative", not an alt field
    return p


# ── Shared residual re-scan validator (promoted from api/handlers.py) ──────────
def verify_residual_scs(fixed_bytes: bytes, filename: str):
    """Re-scan the remediated bytes; return the set of WCAG SCs STILL failing, so a reported
    fix that did not actually clear is never credited. None when the re-scan cannot run — the
    callers treat that as "credit it" (never penalise remediation on an infra hiccup). Uses
    the same SC normalisation (`store._extract_sc`) as the scan traces so the ids line up.

    Single source of truth for the residual re-scan: api/handlers.py `_remediate_file`
    delegates here rather than re-implementing it, so there is exactly one whole-file
    re-scan path (never a second, per-element one)."""
    try:
        import tempfile
        from pathlib import Path as _P

        from scanner import analyse_and_assess
        from store import _extract_sc
        with tempfile.TemporaryDirectory(prefix="acp-verify-") as _d:
            (_P(_d) / filename).write_bytes(fixed_bytes)
            fd, _ = analyse_and_assess(_P(_d), filename, detect_pii=False)
        if not fd:
            return None
        return {sc for i in fd.get("issues", []) if (sc := _extract_sc(i.get("wcag", "")))}
    except Exception:
        return None


# ── 2.4.4 Link Purpose — vague-link detection + deterministic text derivation ──
_VAGUE_LINK = re.compile(
    r"^\s*(?:click|tap|press|go|read|learn|see|view|check(?:\s+it)?\s+out|find\s+out)?\s*"
    r"(?:here|this|link|more|read\s+more|learn\s+more|details?|continue|now|out|"
    r"this\s+link|the\s+link)\s*[.!…]?\s*$", re.I)
_BARE_URL = re.compile(r"^\s*(?:https?://|www\.|mailto:)\S+\s*$", re.I)


def is_vague_link_text(text: str) -> bool:
    """The 2.4.4 predicate: visible link text that conveys nothing about its destination —
    'click here', 'read more', a bare URL, or empty. Mirrors the scanner's link-purpose
    heuristic so a derived replacement that fails this is what clears the re-scan."""
    t = (text or "").strip()
    if not t:
        return True
    return bool(_VAGUE_LINK.match(t) or _BARE_URL.match(t))


# file extension → readable noun for the "(…)" download kind
_EXT_KIND = {"pdf": "PDF", "doc": "Word document", "docx": "Word document",
             "rtf": "document", "txt": "text file", "xls": "spreadsheet",
             "xlsx": "spreadsheet", "csv": "CSV file", "ppt": "presentation",
             "pptx": "presentation", "zip": "ZIP archive", "mp3": "audio file",
             "mp4": "video", "mov": "video"}
_PAGE_EXT = re.compile(r"\.(html?|php|aspx?|jsp)$", re.I)
_SLUG_SPLIT = re.compile(r"[-_.\s]+")


def _humanise(slug: str) -> str:
    """A URL slug → readable Title Case phrase. 'annual-report_2026' → 'Annual Report 2026'.
    Keeps existing acronyms (short all-caps tokens) as-is."""
    s = _PAGE_EXT.sub("", unquote(slug or "").strip())
    parts = [p for p in _SLUG_SPLIT.split(s) if p]
    words = []
    for p in parts:
        words.append(p if (p.isupper() and len(p) <= 5) else p[:1].upper() + p[1:])
    return " ".join(words).strip()


def derive_link_text(href: str, context: str = "") -> dict | None:
    """Deterministically derive descriptive link text from the link TARGET. Returns
    {"text", "rationale", "deterministic": True} or None when the target is too opaque to
    derive from (a bare domain, an id-only query) — the caller then falls back to a local
    text-model draft or human review.

    Deterministic (→ High, auto-applyable) because it reads only the URL, no model:
      * a download whose filename carries the subject:
        'Annual-Report-2026.pdf' → 'Download Annual Report 2026 (PDF)'
      * a readable page path segment: '/about/leadership-team' → 'Leadership team'
      * a mailto: → 'Email <addr>'.
    """
    if not href:
        return None
    href = href.strip()
    m = re.match(r"^mailto:([^?]+)", href, re.I)
    if m:
        addr = m.group(1).strip()
        return {"text": f"Email {addr}", "deterministic": True,
                "rationale": f"derived from the mailto: target ({addr})"}
    try:
        u = urlparse(href)
    except ValueError:
        return None
    seg = posixpath.basename(unquote(u.path or "").rstrip("/"))
    if seg and "." in seg and not _PAGE_EXT.search(seg):
        stem, ext = seg.rsplit(".", 1)
        subject = _humanise(stem)
        kind = _EXT_KIND.get(ext.lower())
        if subject and len(subject) >= 3:
            label = f"Download {subject}" + (f" ({kind})" if kind else "")
            return {"text": label, "deterministic": True,
                    "rationale": f"derived from the download target '{seg}'"}
    elif seg:
        subject = _humanise(seg)
        if subject and len(subject) >= 3 and not subject.replace(" ", "").isdigit():
            return {"text": subject, "deterministic": True,
                    "rationale": f"derived from the page path '/{seg}'"}
    return None


# ── 1.1.1 Decorative-image inference (heuristic — Low, human, NEVER auto) ──────
# Recommending "mark decorative" removes an image from assistive tech. Getting it wrong
# HIDES real content — strictly worse than a missing-alt finding — so this only ever
# produces a Low-confidence proposal a human confirms; it is never auto-applied.
_DECOR_NAME = re.compile(
    r"(?:^|[-_/\s])(logo|divider|spacer|bullet|separator|rule|hr|border|background|bg|"
    r"ornament|flourish|swirl|decoration|decorative|watermark|banner-?bg|line)(?:[-_.\s]|$)",
    re.I)
_DECOR_MIN = 4        # px — below this in either axis is a spacer/hairline
_DECOR_TINY = 24      # px — both axes at/under this is an icon-sized glyph/bullet
_DECOR_THIN_RATIO = 10.0  # aspect ratio at/above which it reads as a divider/rule


def infer_decorative(*, filename: str = "", width: int | None = None,
                     height: int | None = None) -> dict | None:
    """Heuristic guess that an image is decorative (logo / divider / spacer / background
    flourish), or None. Returns {"rationale"} only — the caller surfaces it as a Low proposal
    ("Mark decorative?"), never an auto-fix. Signals, weakest-first: a decorative-sounding
    filename; an extreme aspect ratio (a hairline divider); or a hairline/tiny dimension."""
    name = (filename or "").rsplit("/", 1)[-1]
    nm = _DECOR_NAME.search(name)
    if nm:
        return {"rationale": f"filename '{name}' looks decorative ('{nm.group(1).lower()}')"}
    if width and height:
        if min(width, height) <= _DECOR_MIN:
            return {"rationale": f"{width}×{height}px — a hairline, typical of a spacer/rule"}
        lo, hi = sorted((width, height))
        if lo and hi / lo >= _DECOR_THIN_RATIO:
            return {"rationale": f"{width}×{height}px — extreme aspect ratio, typical of a divider"}
        if width <= _DECOR_TINY and height <= _DECOR_TINY:
            return {"rationale": f"{width}×{height}px — icon-sized, typical of a bullet/glyph"}
    return None


# ── 3.1.2 Language of Parts — per-span language proposals (deterministic) ──────
# The scanner's detector (textchecks.detect_language_parts) fires on multilingual TEXT, not
# on markup — so adding lang attributes can never make it stop firing (a re-scan can't
# validate the fix). Language of Parts is therefore a propose-and-human-approve capability,
# not an auto-fix: we deterministically detect each foreign-language span (langdetect,
# seeded) and hand the reviewer concrete lang codes to approve in one click, rather than a
# blank. It stays fix_mode 'ai-assisted' (already routed to HITL) — we only prefill it.
_LANG_NAMES = {
    "en": "English", "fr": "French", "es": "Spanish", "de": "German", "it": "Italian",
    "pt": "Portuguese", "nl": "Dutch", "sv": "Swedish", "no": "Norwegian", "da": "Danish",
    "fi": "Finnish", "pl": "Polish", "ru": "Russian", "uk": "Ukrainian", "cs": "Czech",
    "ro": "Romanian", "hu": "Hungarian", "tr": "Turkish", "el": "Greek", "ar": "Arabic",
    "he": "Hebrew", "hi": "Hindi", "zh-cn": "Chinese", "zh-tw": "Chinese (Traditional)",
    "ja": "Japanese", "ko": "Korean", "vi": "Vietnamese", "th": "Thai", "id": "Indonesian",
    "ca": "Catalan", "gl": "Galician", "af": "Afrikaans", "sw": "Swahili",
}
_LANG_PROPOSAL_CAP = 25   # bound the work / card count on a heavily multilingual document


def propose_language_parts(text: str) -> list[dict]:
    """Deterministically propose a `lang` code for each foreign-language span in `text`
    (relative to the document's dominant language). Returns [] when langdetect is
    unavailable or the text is single-language — same self-gating as the detector, so this
    never fabricates a span. Each proposal carries the ISO code as `proposed_value` and the
    detected language name + confidence as the rationale; the reviewer approves per span."""
    try:
        import textchecks as _tc
    except Exception:
        return []
    if not text or not _tc._langdetect_available():
        return []
    from langdetect import detect_langs
    segs = [s.strip() for s in _tc._SEG_SPLIT.split(text)
            if len(s.split()) >= _tc._MIN_SEG_WORDS]
    if len(segs) < 2:
        return []
    seen: list[tuple[str, str, float]] = []   # (segment, lang, prob)
    counts: dict[str, int] = {}
    for s in segs[:_tc._MAX_SEGS]:
        try:
            res = detect_langs(s)
        except Exception:
            continue
        if res and res[0].prob >= _tc._MIN_CONF:
            lang = res[0].lang
            counts[lang] = counts.get(lang, 0) + 1
            seen.append((s, lang, res[0].prob))
    if len({lang for lang, n in counts.items() if n >= 1}) < 2:
        return []
    primary = max(counts, key=counts.get)
    out: list[dict] = []
    for seg, lang, prob in seen:
        if lang == primary:
            continue
        name = _LANG_NAMES.get(lang, lang)
        out.append(proposal(
            locator=seg[:60],
            before=seg[:120],
            proposed_value=lang,
            rationale=f"detected {name} (langdetect confidence {prob:.2f}) — mark this passage lang=\"{lang}\"",
            source="langdetect (deterministic language detection)"))
        if len(out) >= _LANG_PROPOSAL_CAP:
            break
    return out


# ── 1.3.3 Sensory Characteristics — non-sensory rewrite proposal (model, human) ─
# Genuinely subjective (which green button?), so this ALWAYS surfaces for human approval and
# is never auto-applied. The local text model drafts a non-sensory rewrite the reviewer
# accepts or edits — turning a from-scratch rewrite into a one-click confirm. Degrades to []
# (plain HITL deferral) when the model is unavailable.
_SENSORY_SENT = re.compile(r"[^.!?\n]*[.!?\n]|[^.!?\n]+")
_SENSORY_CAP = 5


def propose_sensory_rewrite(text: str, *, filename: str = "", ai_enabled: bool = True) -> list[dict]:
    """Propose a non-sensory rewrite for each sentence that relies on shape / colour / size /
    position (WCAG 1.3.3). Returns [] when AI is off/unavailable or nothing matches. The
    proposals are always Low confidence (a subjective judgement) — the caller surfaces them
    for human approval, never auto-applies."""
    if not text or not ai_enabled:
        return []
    try:
        import textchecks as _tc
    except Exception:
        return []
    try:
        import ai as _ai
        if not _ai.is_available():
            return []
    except Exception:
        return []
    out: list[dict] = []
    seen: set[str] = set()
    for sm in _tc._SENSORY_RE.finditer(text):
        # widen the match to the whole sentence it sits in, so the rewrite has context
        s = sm.start()
        left = text.rfind(".", 0, s) + 1
        right = text.find(".", sm.end())
        sentence = text[left:(right + 1 if right != -1 else len(text))].strip()
        sentence = re.sub(r"\s+", " ", sentence)[:240]
        if not sentence or sentence in seen:
            continue
        seen.add(sentence)
        try:
            res = _ai.suggest_fix("1.3.3", "Sensory Characteristics", "A", filename, detail=sentence)
        except Exception:
            res = None
        if not res or not res.get("suggestion"):
            continue
        out.append(proposal(
            locator=sentence[:60],
            before=sentence,
            proposed_value=res["suggestion"],
            rationale="instruction relies on a sensory characteristic (shape / colour / position); "
                      "confirm the rewrite names the right control",
            source=f"AI text model ({res.get('model', 'llama')}) — human judgement required"))
        if len(out) >= _SENSORY_CAP:
            break
    return out


# ── 1.3.1 / 2.4.6 Heading level inference (deterministic — from font-size rank) ─
def infer_heading_levels(sizes) -> dict:
    """Map a set of pseudo-heading font sizes → heading levels by descending rank: the
    largest distinct size is Heading 1, the next Heading 2, … clamped at Heading 6 (deeper
    ranks all collapse to 6, since WCAG only defines h1–h6). Deterministic: same sizes →
    same levels every run, so the inferred level is a High-confidence derivation, not a
    guess. `sizes` is any iterable of numbers (points/half-points — only the ORDER matters)."""
    distinct = sorted({float(s) for s in sizes if s is not None}, reverse=True)
    return {sz: min(i + 1, 6) for i, sz in enumerate(distinct)}
