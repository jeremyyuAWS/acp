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

_TEXT_GATE — which availability probe a model-backed proposer may gate on
------------------------------------------------------------------------
Every proposer here that drafts a value (`ai.suggest_fix`, `ai.simplify_text`) needs the
configured TEXT model, so it gates on `ai.model_is_available()`. It must NOT gate on
`ai.is_available()`, which only answers "did Ollama's /api/tags respond".

The two came apart on 2026-07-29: an Ollama was reachable but had never pulled OLLAMA_MODEL,
so `is_available()` was true, every `/api/generate` returned 404 "model not found", and each
proposer returned []. An empty proposal list is exactly what a clean document produces — so
the pipeline reported "no proposals for this finding" and the missing model never surfaced.
Gating on capability instead of reachability makes the difference visible (ai.py logs the
missing model once) and stops one wasted 404 per finding.

`ocr.is_available()` in propose_images_of_text is unrelated — that is tesseract, no model.
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
#                    "AI vision model (<model>)"), which also encodes the honesty tier.
#                    The vision provenance names the model that actually ran (res["model"]),
#                    never a hardcoded name — so a model swap can't leave a lie in the trail.
#   thumb          — optional base64 image thumbnail for image proposals.
#   explain_only   — see below. Default (absent) means the value is content to write back.
#
# EXPLAIN-ONLY proposals. Nearly every proposal's `proposed_value` is content destined for the
# document, and the certify gate is built on that: store.count_unapplied_approved_values counts
# any approved row holding a locator + value, so a file cannot certify until an applier has
# written those values in and marked the row applied.
#
# A few proposals are not like that. A PDF structure/heading map, or a page reading order, is
# derived and handed to a human to CONFIRM — the approved map is the tagging instruction for
# re-authoring and the compliance evidence of what the structure should be. Re-tagging a PDF
# re-authors the file (ADR 0016), so nothing is ever written back, and no applier will ever
# mark the row applied. Left unflagged such a card is a trap: the reviewer confirms the map,
# the gate counts a promise no writer can keep, and the file can never certify or reach
# Publish — permanently, on an approval that was entirely correct.
#
# `explain_only=True` says "this value IS the deliverable; it is never written into the file".
# store._row_approved_values skips those values, so confirming the card resolves the finding
# instead of blocking it. The flag lives on the PROPOSAL, not on the reviewer's action, because
# _row_approved_values falls back to `proposed_value` when a client sends no approved value —
# any client-side suppression would be undone by that fallback.
#
# The alternative for such a card is to not offer it at all (WCAG 2.4.4 Link Purpose on PDF went
# that way: see tests/test_pdf_link_purpose_explain_only.py). That is right when the value is
# only useful once written — an unwritten link label helps nobody. It is wrong here, where the
# confirmed map is the useful artefact.


def proposal(locator, before, proposed_value, rationale, source, thumb=None, kind=None,
             explain_only=False, sc=None, why_review=None, context=None) -> dict:
    """One review card's worth of state.

    `why_review` and `context` exist because of what a reviewer was previously NOT told. A card
    arrived with a draft, a model name and a picture, and no answer to the first question a
    reviewer actually asks: *why is this one mine?* ACP knows — the split between an auto-applied
    fix and a proposal is not arbitrary, it is whether the draft is GROUNDED in something the
    document itself contains (the image's own OCR text, a caption, a native chart's series). An
    ungrounded draft is a guess, and saying so converts the card from "approve this alt text"
    into "this is a guess, and here is why we could not check it" — which is a different and much
    faster judgement to make.

    Without it the reviewer has to re-derive the whole assessment to decide whether to trust the
    draft, which is precisely the low-value human work the review lane is supposed to remove.
    """
    p = {"locator": locator, "before": before, "proposed_value": proposed_value,
         "rationale": rationale, "source": source}
    if why_review:
        p["why_review"] = why_review
    if context:
        # What surrounds the thing being judged — a caption, the sentence a link sits in, the
        # paragraph before an image. A reviewer deciding whether alt text is right needs the same
        # context a reader would have; a card showing an image with no surrounding text asks them
        # to judge it more blindly than the screen-reader user they are judging it for.
        p["context"] = context
    if thumb:
        p["thumb"] = thumb
    if kind:
        p["kind"] = kind   # e.g. 'decorative' → the card offers "Mark decorative", not an alt field
    if explain_only:
        p["explain_only"] = True
    if sc:
        # WHICH criterion this proposal answers. Optional, and absent means 1.1.1 — every
        # proposal remediate_office produced before this was a vision alt, and the caller
        # (handlers._enqueue_proposals) hard-coded that SC. Once one function returns proposals
        # for several criteria the label has to travel WITH the proposal, or a link-text draft
        # lands on a 1.1.1 review card and the reviewer is asked to approve alt text that is not
        # alt text.
        #
        # Left optional rather than required so the existing callers keep working unchanged; the
        # default lives in the consumer, next to the routing decision it feeds.
        p["sc"] = sc
    return p


def thumb_b64(img_bytes: bytes, *, max_edge: int = 96) -> str | None:
    """A small base64 PNG data-URL of an image, so a review card can show the thing being
    judged. Promoted here from remediate_office because every VISUAL proposal needs it: the
    reviewer is deciding *about an image* — is this logo decorative? is this the reading order
    of this page? — and a card with no picture asks them to approve a claim they cannot check.

    max_edge is the longest side in pixels. 96 suits an image embedded in a document and shown
    at card size; a whole rendered page needs more to stay legible.

    Best-effort: any decode/resize/encode failure returns None. A missing thumbnail must never
    affect remediation, and a proposal without one still renders (ProposalThumb drops it) — it
    just carries less evidence."""
    try:
        import base64
        import io as _io
        from PIL import Image
        im = Image.open(_io.BytesIO(img_bytes))
        im.load()
        if im.mode not in ("RGB", "RGBA"):
            im = im.convert("RGB")
        w, h = im.size
        longest = max(w, h) or 1
        if longest > max_edge:
            r = max_edge / longest
            im = im.resize((max(1, round(w * r)), max(1, round(h * r))), Image.LANCZOS)
        buf = _io.BytesIO()
        im.save(buf, format="PNG", optimize=True)
        return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception:
        return None


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
# Per-channel stddev (0–255) below which an image reads as a near-solid fill. Kept deliberately
# TIGHT: the decorative call is computed on a 64×64 downscale, which averages sparse dark text into
# its white background — a page of text (e.g. an image-of-text notice) can fall to a stddev of ~6.
# Marking such an image decorative HIDES its text from screen readers (the expensive, harmful error
# direction), so only a genuinely flat fill (stddev ≈0–2) qualifies; anything with structure is left
# for the vision model / a human. Under-calling decorative just adds a review; over-calling erases
# content.
_DECOR_STD = 3.0


def _near_uniform(image: bytes | None) -> dict | None:
    """Content signal that an image is decorative: a near-solid fill — a black/white/colour
    background block or a flat gradient with no meaningful detail. Computed from the pixels
    (not the name or size), so it catches the ordinary-named background blocks the other
    signals miss — exactly the images a vision model can only describe as "black background,
    nothing to describe". Conservative on purpose: only genuinely flat images pass, because a
    real photo or chart has high per-channel variance and marking real content decorative is
    the expensive error. Never raises — an undecodable image is simply not classified here."""
    if not image:
        return None
    try:
        from io import BytesIO

        from PIL import Image, ImageStat
        im = Image.open(BytesIO(image))
        im.draft("RGB", (64, 64))              # fast partial decode where the codec supports it
        im = im.convert("RGB")
        im.thumbnail((64, 64))
        std = ImageStat.Stat(im).stddev
    except Exception:
        return None
    if std and max(std) < _DECOR_STD:
        return {"rationale": f"the image is a near-solid fill (colour variance ≈{max(std):.0f}/255) "
                             "— no meaningful visual content"}
    return None


def infer_decorative(*, filename: str = "", width: int | None = None,
                     height: int | None = None, image: bytes | None = None) -> dict | None:
    """Heuristic guess that an image is decorative (logo / divider / spacer / background
    flourish), or None. Returns {"rationale"} only — the caller surfaces it as a Low proposal
    ("Mark decorative?"), never an auto-fix. Signals, weakest-first: a decorative-sounding
    filename; a near-solid pixel fill (a background block); an extreme aspect ratio (a hairline
    divider); or a hairline/tiny dimension."""
    name = (filename or "").rsplit("/", 1)[-1]
    nm = _DECOR_NAME.search(name)
    if nm:
        return {"rationale": f"filename '{name}' looks decorative ('{nm.group(1).lower()}')"}
    # Size signals first — a hairline / icon / divider gets a precise dimensional rationale.
    if width and height:
        if min(width, height) <= _DECOR_MIN:
            return {"rationale": f"{width}×{height}px — a hairline, typical of a spacer/rule"}
        lo, hi = sorted((width, height))
        if lo and hi / lo >= _DECOR_THIN_RATIO:
            return {"rationale": f"{width}×{height}px — extreme aspect ratio, typical of a divider"}
        if width <= _DECOR_TINY and height <= _DECOR_TINY:
            return {"rationale": f"{width}×{height}px — icon-sized, typical of a bullet/glyph"}
    # …then the content signal, for a normal-sized image that is nonetheless a solid fill.
    return _near_uniform(image)


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


def _despace_ocr(seg: str) -> str:
    """Collapse OCR letter-spacing artifacts ("t r i mest r i el") so language detection can
    work on text rendered inside images. When most tokens are 1–2 chars the spaces carry no
    word-boundary information — drop them and let langdetect's character n-grams (which don't
    need word boundaries) identify the language. Returns the segment unchanged otherwise."""
    toks = seg.split()
    # Real OCR fragments are pure letters split apart — a slash-list or numbered line
    # ("4 frontier / mini / nano") must never be joined into pseudo-words (that minted a
    # confident-but-wrong "Italian" on a real corpus document).
    if len(toks) < 4 or not all(t.isalpha() for t in toks):
        return seg
    frag = sum(1 for t in toks if len(t) <= 2)
    return "".join(toks) if frag / len(toks) >= 0.35 else seg


def language_parts_suggestion(text: str) -> dict | None:
    """One-shot deterministic draft for a 3.1.2 review card: WHICH language the foreign
    passage(s) are in, with the actual passages as evidence. Replaces the generic text-model
    template that produced rule-mismatched nonsense for this criterion — the language of a
    passage is machine-detectable (langdetect, seeded), so the card should arrive answered,
    not ask the reviewer to author it. Real detections only, never a fabricated score
    (ADR 0016); returns None when nothing detects confidently (the card degrades to manual)."""
    try:
        import textchecks as _tc
    except Exception:
        return None
    if not text or not _tc._langdetect_available():
        return None
    import html as _html
    text = _html.unescape(text)   # same entity decode as the detector ('r&#233;gions' → 'régions')
    from langdetect import detect_langs
    counts: dict[str, int] = {}
    samples: dict[str, str] = {}          # first (original, human-readable) passage per lang
    scanned = 0
    for raw in _tc._SEG_SPLIT.split(text):
        seg = raw.strip()
        if not seg or _tc._looks_like_code(seg):
            continue
        # Normal prose gates on word count; OCR-despaced text has no words, so it gates on
        # character length instead (langdetect needs ~25+ chars to be trustworthy).
        if len(seg.split()) >= _tc._MIN_SEG_WORDS:
            cand = seg
        else:
            d = _despace_ocr(seg)
            cand = d if (d != seg and len(d) >= 25) else None
        if cand is None:
            continue
        scanned += 1
        try:
            res = detect_langs(cand)
        except Exception:
            continue
        if res and res[0].prob >= _tc._MIN_CONF:
            lang = res[0].lang
            counts[lang] = counts.get(lang, 0) + 1
            samples.setdefault(lang, seg)
        if scanned >= _tc._MAX_SEGS:
            break
    # A genuine MIX is required — one language across the whole text is the document's
    # primary language (3.1.1's concern), and suggesting it as a "part" would be wrong.
    if len(counts) < 2:
        return None
    # The parts needing lang markup are the minority languages.
    primary = max(counts, key=counts.get)
    foreign = [lang for lang in counts if lang != primary]
    lines = []
    for lang in sorted(foreign, key=lambda code: -counts[code])[:3]:
        name = _LANG_NAMES.get(lang, lang)
        snippet = samples[lang][:110]
        lines.append(f'{name}: mark the passage lang="{lang}" — detected in “{snippet}”')
    return {
        "suggestion": "\n".join(lines),
        "kind": "language tag",
        "is_template": False,
        "deterministic": True,
        "model": "langdetect (deterministic)",
        "languages": [{"code": lang, "name": _LANG_NAMES.get(lang, lang),
                       "passages": counts[lang]} for lang in foreign],
    }


# ── 1.3.3 Sensory Characteristics — non-sensory rewrite proposal (model, human) ─
# Genuinely subjective (which green button?), so this ALWAYS surfaces for human approval and
# is never auto-applied. The local text model drafts a non-sensory rewrite the reviewer
# accepts or edits — turning a from-scratch rewrite into a one-click confirm. Degrades to []
# (plain HITL deferral) when the model is unavailable.
_SENSORY_SENT = re.compile(r"[^.!?\n]*[.!?\n]|[^.!?\n]+")
_SENSORY_CAP = 5


def propose_sensory_rewrite(text: str, *, filename: str = "", ai_enabled: bool = True,
                            guidance: str = "") -> list[dict]:
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
        # ai.suggest_fix below drafts with the TEXT model, so the gate must be
        # model_is_available() — see the note on _TEXT_GATE at the top of this module.
        if not _ai.model_is_available():
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
        # NOTE (2026-07-11): a GPU precision filter was tried here (skip the rewrite when the
        # model says the instruction also names its control) and REJECTED after live corpus
        # validation: llama3.2 returned descriptive phrases ("green button") as "names" and
        # suppressed a genuine finding's rewrite. A filter that can silently kill a real
        # rewrite loses more than it saves — every regex hit keeps its draft, and the human
        # dismisses false positives with one click.
        try:
            res = _ai.suggest_fix("1.3.3", "Sensory Characteristics", "A", filename,
                                  detail=sentence, guidance=guidance)
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


# ── 3.1.5 Reading Level — plain-language rewrite of the densest sentences (GPU-assisted) ─
_READING_CAP = 5


def propose_reading_level(text: str, *, filename: str = "", ai_enabled: bool = True) -> list[dict]:
    """Propose a plain-language rewrite of the hardest sentences (WCAG 3.1.5). Self-gates on the same
    detector the scan uses (textchecks.detect_reading_level) so it only fires when the document really
    reads above the SC bar, then targets the densest sentences and asks the local text model to
    simplify each while PRESERVING every fact. Always Low confidence — surfaced for human approval,
    never auto-applied (rewriting prose is a judgement, and a bad simplification could drop meaning)."""
    if not text or not ai_enabled:
        return []
    try:
        import textchecks as _tc
        import ai as _ai
    except Exception:
        return []
    # model_is_available(): the rewrite below is ai.simplify_text, a TEXT-model call (_TEXT_GATE).
    if not _tc.detect_reading_level(text) or not _ai.model_is_available():
        return []

    def _density(s: str) -> float:
        words = _tc._WORD_RE.findall(s)
        if not words:
            return 0.0
        return len(words) * (sum(_tc._syllables(w) for w in words) / len(words))

    def _is_prose(s: str) -> bool:
        # Skip flattened lists / heading blobs — multiple labels, or mostly Title-Case words: those
        # aren't sentences to simplify (the model refuses them anyway, wasting a call).
        if s.count(":") >= 2:
            return False
        words = s.split()
        lower = sum(1 for w in words if w[:1].islower())
        return len(words) >= 15 and lower >= 0.5 * len(words)

    # Real prose only: 15–60 words. Below is a fragment; ABOVE is almost always an extraction blob
    # (a flattened table/list with no sentence punctuation) — simplifying those is meaningless.
    sents = {re.sub(r"\s+", " ", s).strip()
             for s in re.split(r"(?<=[.!?])\s+", text)
             if 15 <= len(s.split()) <= 60 and _is_prose(re.sub(r"\s+", " ", s).strip())}
    def _fk_grade(s: str) -> float | None:
        # Single-sentence Flesch-Kincaid (n_sent=1) — a real measurement the reviewer can see,
        # not a confidence guess. Noisier than a document-level score, so it is labelled ≈.
        words = _tc._WORD_RE.findall(s)
        if not words:
            return None
        return 0.39 * len(words) + 11.8 * (sum(_tc._syllables(w) for w in words) / len(words)) - 15.59

    ranked = sorted(sents, key=_density, reverse=True)[:_READING_CAP]
    out: list[dict] = []
    for s in ranked:
        s = s[:600]
        simpler = _ai.simplify_text(s, file=filename)
        if not simpler or simpler.strip().lower() == s.strip().lower():
            continue
        grade = _fk_grade(s)
        measured = (f"this sentence alone scores Flesch-Kincaid grade ≈{grade:.0f} "
                    f"(the SC targets ~grade 9)" if grade is not None
                    else "this sentence reads well above the target level")
        out.append(proposal(
            locator=s[:60],
            before=s,
            proposed_value=simpler,
            rationale=f"{measured}; confirm the simpler version keeps every fact and number",
            source="AI text model (plain-language rewrite) — human judgement required"))
    return out


# ── 1.4.5 Images of Text (OCR the text back out — reviewer pastes it as real text) ─
def propose_images_of_text(path, ext: str) -> list[dict]:
    """One WCAG 1.4.5 proposal per embedded image that bakes in substantial text: the text is
    OCR'd out and surfaced so the reviewer can paste it back as real, selectable text (or
    confirm the picture is decorative). NEVER auto-applied — swapping an image for live text is
    an authoring decision, and OCR misreads — so this is a Medium-confidence card, not a silent
    fix. Deterministic (tesseract, api/ocr.py), no model. Returns [] when OCR is
    unavailable/disabled or nothing text-bearing is found, so it is safe to run on every
    remediated file. Covers BOTH scan tiers so neither finding is left without a review path:
    the AA band (ocr.images_of_text's floor — `_MIN_WORDS` words above `_MIN_PIXELS`) gets the
    paste-back-as-text card, and the strict-only band (1.4.9's lower floor) gets a card that
    also offers the logotype/essential-exception disposition, since a short baked-in text block
    is very often a brand mark WCAG exempts under both SCs."""
    import ocr as _ocr
    if not _ocr.is_available():
        return []
    try:
        images = _ocr._embedded_images(path, (ext or "").lower())
    except Exception:
        return []
    out: list[dict] = []
    for i, img in enumerate(images):
        try:
            # Band determination uses the scan's own functions at the scan's own floors, so
            # the card and the finding can never disagree about which tier an image is in.
            aa_band = _ocr._ocr_words(img, _ocr._MIN_PIXELS) >= _ocr._MIN_WORDS
            words = _ocr._ocr_words(img, _ocr._MIN_PIXELS_STRICT)
            if not aa_band and words < _ocr._MIN_WORDS_STRICT:
                continue                       # icon / single-glyph — no images-of-text finding at all
            text = " ".join(_ocr.ocr_text(img).split())
            if not text:
                continue                       # OCR gave nothing usable — no fabricated value
            if aa_band:
                # AA band — a substantial text block baked into pixels. The scan's 1.4.5 finding.
                rationale = ("WCAG 1.4.5: text presented as an image should be real, selectable "
                             "text. Paste this back into the document (or mark the image "
                             "decorative if the text is duplicated nearby).")
            else:
                # Strict-only band (fails 1.4.9/AAA but not 1.4.5/AA): a short text block —
                # often a logotype or badge, which WCAG treats as ESSENTIAL (exempt) under both
                # SCs. The card offers that disposition explicitly instead of leaving the
                # finding with no review path at all.
                rationale = (f"WCAG 1.4.9 (AAA): a short text block ({words} words) is baked into "
                             "this image. If it is a logotype/brand mark, WCAG treats it as "
                             "essential — record the logotype exception. Otherwise paste the "
                             "text back as real, selectable text.")
                # GPU hint (best-effort, never a decision): a vision look at the image itself.
                # Only the strict band — AA-band blocks are substantial text, not brand marks —
                # and only a POSITIVE read is surfaced: "the model didn't think it's a logo" is
                # not evidence of anything, so silence beats noise (ADR 0016).
                try:
                    import ai as _ai
                    if _ai.looks_like_logotype(img):
                        rationale = ("The vision model reads this image as a logotype/brand "
                                     "mark. " + rationale)
                except Exception:
                    pass
            out.append(proposal(
                locator=f"image {i + 1}",
                before="text baked into an image — assistive technology cannot read it",
                proposed_value=text,
                rationale=rationale,
                source="OCR (tesseract) — human confirmation required",
                thumb=thumb_b64(img),
            ))
        except Exception:
            continue                           # one bad image never sinks the rest
    return out


# ── 2.4.4 / 2.4.9 Office link text — descriptive-text proposals (docx + pptx) ──
# The html lane's exact pattern, ported to OOXML: a VAGUE link ("click here", a bare URL)
# gets a deterministic derivation from its target when possible (High) or a local text-model
# draft (Medium); a link whose display text is REUSED for a different destination (the 2.4.9
# ambiguity the detector flags) gets the same treatment per destination. Proposal-only for
# Office — rewriting run text is an authoring edit a human approves, never silent.
_LINK_PROPOSAL_CAP = 20


def extract_office_links(path, ext: str) -> list[tuple[str, str]]:
    """(display_text, href) for every hyperlink in a docx/pptx — the same OOXML parsing as
    the 2.4.9 detector (office_structure), so proposer and detector see identical links."""
    import zipfile
    import office_structure as _os
    ext = (ext or "").lower().lstrip(".")
    out: list[tuple[str, str]] = []
    try:
        with zipfile.ZipFile(path) as zf:
            if ext == "docx":
                doc = _os._read(zf, "word/document.xml") or ""
                rels = _os._relationships(zf, "word/_rels/document.xml.rels")
                for rid, inner in _os._HYPERLINK.findall(doc):
                    href = rels.get(rid)
                    if href:
                        out.append(("".join(_os._WT.findall(inner)), href))
            elif ext == "pptx":
                import re as _re
                for slide_name in sorted(n for n in zf.namelist()
                                         if _re.fullmatch(r"ppt/slides/slide\d+\.xml", n)):
                    xml = _os._read(zf, slide_name) or ""
                    num = _re.search(r"slide(\d+)\.xml", slide_name).group(1)
                    rels = _os._relationships(zf, f"ppt/slides/_rels/slide{num}.xml.rels")
                    for run_inner in _os._A_RUN.findall(xml):
                        m = _os._A_HLINK.search(run_inner)
                        if not m:
                            continue
                        href = rels.get(m.group(1))
                        if href:
                            out.append(("".join(_os._AT.findall(run_inner)), href))
            elif ext == "xlsx":
                # Cell hyperlinks: <hyperlink ref="A1" r:id="rId1" display="click here"/>. The
                # detector (office_structure.xlsx_structure_checks) judges the `display` text, so
                # the proposer reads the SAME attribute — a link with no display is skipped there
                # and here alike (its label is the cell value, which we don't rewrite blindly).
                import re as _re
                for ws_name in sorted(n for n in zf.namelist()
                                      if _re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n)):
                    xml = _os._read(zf, ws_name) or ""
                    num = _re.search(r"sheet(\d+)\.xml", ws_name).group(1)
                    rels = _os._relationships(zf, f"xl/worksheets/_rels/sheet{num}.xml.rels")
                    for tag in _os._XLSX_HL.findall(xml):
                        disp = _os._HL_DISPLAY.search(tag)
                        rid = _re.search(r'r:id="(rId\w+)"', tag)
                        if not disp or not rid:
                            continue
                        href = rels.get(rid.group(1))
                        if href:
                            out.append((disp.group(1), href))
    except Exception:
        return []
    return out


def propose_link_texts(path, ext: str, *, ai_enabled: bool = True, guidance: str = "") -> list[dict]:
    """Descriptive link-text proposals for a docx/pptx/xlsx. Each proposal carries `sc` ('2.4.4'
    for vague text, '2.4.9' for text reused across destinations) so the caller enqueues it
    onto the right card. Self-gating: a document whose links are all descriptive and unique
    yields [] — safe to run on every remediated Office file.

    Where this stands relative to the DETECTORS, stated exactly rather than assumed as parity.
    It matters because an approved value is credited only when a re-scan no longer reports the
    criterion (handlers._apply_one_value_kind): a proposal carrying an `sc` this format has no
    detector for is approvable but never creditable, and the criterion would be cleared on a
    re-scan that never looked for it.

      * 2.4.4 — detected on all three formats (office_structure._vague_link_findings). The
        predicate here is NOT the detector's function: is_vague_link_text matches phrasings
        ("view details", "check it out") that the detector's word list does not, so this
        proposes a superset. That direction is the safe one — the extra card only improves
        text the detector never called a failure, and nothing gets credited unverified.
      * 2.4.9 — detected for docx/pptx only (_duplicate_href_findings). xlsx has no
        duplicate-display-text check, so no 2.4.9 proposal is raised there.
    """
    links = extract_office_links(path, ext)
    if not links:
        return []
    # Text reused for a DIFFERENT destination — the 2.4.9 signal, the same comparison
    # _duplicate_href_findings makes, and only for the formats that actually make it.
    by_text: dict[str, set[str]] = {}
    if (ext or "").lower().lstrip(".") in ("docx", "pptx"):
        for text, href in links:
            t = " ".join((text or "").split()).lower()
            if t:
                by_text.setdefault(t, set()).add(href)
    ambiguous = {t for t, hrefs in by_text.items() if len(hrefs) > 1}

    out: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for text, href in links:
        norm = " ".join((text or "").split()).lower()
        vague = is_vague_link_text(text)
        dup = norm in ambiguous
        if not (vague or dup) or (norm, href) in seen:
            continue
        seen.add((norm, href))
        sc = "2.4.4" if vague else "2.4.9"
        why = ("link text conveys nothing about the destination" if vague
               else "the same link text points at a different destination elsewhere in the document")
        der = derive_link_text(href, "")
        if der:
            out.append({**proposal(
                locator=href, before=text or "(empty link text)",
                proposed_value=der["text"],
                rationale=f"{why} — {der['rationale']}",
                source="derived from the link target"), "sc": sc})
        elif ai_enabled:
            try:
                import ai as _ai
                # model_is_available(), not is_available() — suggest_fix drafts the replacement
                # link text with the TEXT model (_TEXT_GATE).
                res = (_ai.suggest_fix(sc, "Link Purpose", "A", "",
                                       detail=f'link text "{text}" → {href}', guidance=guidance)
                       if _ai.model_is_available() else None)
            except Exception:
                res = None
            if res and res.get("suggestion"):
                out.append({**proposal(
                    locator=href, before=text or "(empty link text)",
                    proposed_value=res["suggestion"],
                    rationale=f"{why}; the target is opaque, so AI drafted descriptive text — "
                              "confirm it names the destination",
                    source=f"AI text model ({res.get('model', 'llama')})"), "sc": sc})
        if len(out) >= _LINK_PROPOSAL_CAP:
            break
    return out


# ── 2.4.10 Section Headings — AI-drafted heading proposals (docx) ──────────────
# The detector (office_structure DOCX_NO_SECTION_HEADINGS) fires when a long document uses
# no heading styles at all. Sectioning is an authoring decision, so this NEVER auto-inserts;
# it splits the document at its own blank-paragraph boundaries and drafts one short heading
# per section for a human to approve, with each section's opening words as the evidence.
_SECTION_HEADING_CAP = 8      # a review card with 30 headings is homework, not assistance
_MIN_SECTION_WORDS = 25       # a heading for a two-line fragment is noise


def propose_section_headings(path, ext: str, *, ai_enabled: bool = True, guidance: str = "") -> list[dict]:
    """Heading proposals for a long, heading-less docx. Gates on the DETECTOR's own
    conditions (no Heading styles, >= its paragraph floor) so a card can never appear for a
    document the scan didn't flag; degrades to [] when AI is off/unavailable (the finding
    stays plain human review). Sections come from the document's own blank-line structure —
    the model only names them, it never invents where they are."""
    if (ext or "").lower().lstrip(".") != "docx" or not ai_enabled:
        return []
    import zipfile

    import office_structure as _os
    try:
        with zipfile.ZipFile(path) as zf:
            doc = _os._read(zf, "word/document.xml") or ""
    except Exception:
        return []
    if _os._HEADING_STYLE.search(doc):
        return []                                  # has headings — not this finding
    paras = ["".join(_os._WT.findall(p)).strip() for p in _os._PARA.findall(doc)]
    if sum(1 for p in paras if p) < _os._MIN_PARAS_FOR_HEADINGS:
        return []                                  # short memo — detector wouldn't fire
    # Sections = runs of non-empty paragraphs split at the document's blank paragraphs.
    sections: list[tuple[int, str]] = []           # (1-based paragraph number, section text)
    cur: list[str] = []
    start = 0
    for i, p in enumerate(paras):
        if p:
            if not cur:
                start = i + 1
            cur.append(p)
        elif cur:
            sections.append((start, " ".join(cur)))
            cur = []
    if cur:
        sections.append((start, " ".join(cur)))
    sections = [(n, t) for n, t in sections if len(t.split()) >= _MIN_SECTION_WORDS]
    if len(sections) < 2:
        return []                                  # one blob — no section structure to name
    try:
        import ai as _ai
        # TEXT model — suggest_fix names each section below (_TEXT_GATE).
        if not _ai.model_is_available():
            return []
    except Exception:
        return []
    out: list[dict] = []
    for n, text in sections[:_SECTION_HEADING_CAP]:
        try:
            res = _ai.suggest_fix("2.4.10", "Section Headings", "AAA", "",
                                  detail=text[:400], guidance=guidance)
        except Exception:
            res = None
        title = (res or {}).get("suggestion", "").strip().strip('"')
        if not title or len(title) > 90:
            continue
        out.append(proposal(
            locator=f"before paragraph {n}",
            before="(no section heading — a long document reads as one undifferentiated block)",
            proposed_value=title,
            rationale=f"AI named this section from its opening words — “{text[:110]}…” — "
                      "confirm the heading describes it",
            source=f"AI text model ({(res or {}).get('model', 'llama')})"))
    return out


# ── pptx 2.4.6 — AI slide-title drafts for empty title placeholders ─────────────
_SLIDE_TITLE_CAP = 10


def propose_slide_titles(path, ext: str, *, ai_enabled: bool = True, guidance: str = "") -> list[dict]:
    """A slide whose layout has a title placeholder that was left EMPTY (the detector's
    PPTX_TITLE_EMPTY condition, mirrored exactly) gets an AI-drafted title from the slide's
    own body text — naming content is drafting, placement is already decided by the layout.
    One proposal per offending slide, the slide's opening words as evidence; [] when AI is
    off/unavailable or every title is filled."""
    if (ext or "").lower().lstrip(".") != "pptx" or not ai_enabled:
        return []
    import re as _re
    import zipfile

    import office_structure as _os
    empties: list[tuple[int, str]] = []        # (slide number, slide body text)
    try:
        with zipfile.ZipFile(path) as zf:
            for slide_name in sorted(n for n in zf.namelist()
                                     if _re.fullmatch(r"ppt/slides/slide\d+\.xml", n)):
                xml = _os._read(zf, slide_name) or ""
                ph = _os._PPTX_TITLE_PH.search(xml)
                if not ph:
                    continue                   # no title slot on this layout — by design
                shape_text = xml[ph.end():].split("</p:sp>", 1)[0]
                if "".join(_os._AT.findall(shape_text)).strip():
                    continue                   # title filled — not this finding
                body = " ".join(t for t in _os._AT.findall(xml) if t.strip())
                if body.strip():
                    empties.append((int(_re.search(r"slide(\d+)", slide_name).group(1)), body))
    except Exception:
        return []
    if not empties:
        return []
    try:
        import ai as _ai
        # TEXT model — suggest_fix names each untitled slide below (_TEXT_GATE).
        if not _ai.model_is_available():
            return []
    except Exception:
        return []
    out: list[dict] = []
    for num, body in empties[:_SLIDE_TITLE_CAP]:
        try:
            res = _ai.suggest_fix("2.4.6", "Headings and Labels", "AA", "",
                                  detail=f"slide content: {body[:400]}", guidance=guidance)
        except Exception:
            res = None
        title = (res or {}).get("suggestion", "").strip().strip('"')
        if not title or len(title) > 90:
            continue
        out.append(proposal(
            locator=f"slide {num}",
            before="(title placeholder left empty — the slide has no announceable name)",
            proposed_value=title,
            rationale=f"AI named the slide from its own content — “{body[:110]}…” — "
                      "confirm the title describes it",
            source=f"AI text model ({(res or {}).get('model', 'llama')})"))
    return out


# ── xlsx 2.4.6 — AI-drafted names for default sheet tabs / table columns ────────
_XLSX_LABEL_CAP = 12


def propose_xlsx_labels(path, ext: str, *, ai_enabled: bool = True, guidance: str = "") -> list[dict]:
    """xlsx 2.4.6 Headings & Labels — default 'SheetN' tabs and 'ColumnN' table headers get an
    AI-drafted meaningful name from their OWN content (the sheet's cells / the column's values),
    mirroring the detector's gate exactly (>= 2 default sheet tabs, or any default table column).
    Naming is drafting — the model only labels content that already exists; a human approves.
    [] when AI is off/unavailable or nothing is default-named."""
    if (ext or "").lower().lstrip(".") != "xlsx" or not ai_enabled:
        return []
    import re as _re
    import zipfile

    import office_structure as _os
    targets: list[tuple[str, str, str]] = []      # (locator, before, sample content)
    try:
        with zipfile.ZipFile(path) as zf:
            ss_xml = _os._read(zf, "xl/sharedStrings.xml") or ""
            shared = _re.findall(r"<t[^>]*>(.*?)</t>", ss_xml, _re.S)     # <si> text, rich runs concatenated

            def sample(ws_xml: str, col: str | None = None, limit: int = 15) -> str:
                out: list[str] = []
                for m in _re.finditer(r'<c\b[^>]*\br="([A-Z]+)\d+"[^>]*?(?:\st="([^"]*)")?[^>]*>(.*?)</c>', ws_xml, _re.S):
                    if col and m.group(1) != col:
                        continue
                    inner, typ = m.group(3), m.group(2)
                    v = _re.search(r"<v>(.*?)</v>", inner)
                    if v and typ == "s":
                        idx = int(v.group(1))
                        if 0 <= idx < len(shared) and shared[idx].strip():
                            out.append(shared[idx].strip())
                    elif v and v.group(1).strip():
                        out.append(v.group(1).strip())
                    else:
                        t = _re.search(r"<t[^>]*>(.*?)</t>", inner, _re.S)
                        if t and t.group(1).strip():
                            out.append(t.group(1).strip())
                    if len(out) >= limit:
                        break
                return " · ".join(out[:limit])

            # 2.4.6a — default sheet tabs (only when >= 2, matching the detector).
            wb = _os._read(zf, "xl/workbook.xml") or ""
            wb_rels = _os._relationships(zf, "xl/_rels/workbook.xml.rels")
            # attr order varies — pull name + r:id independently per <sheet> tag.
            sheets = []
            for tag in _re.findall(r"<sheet\b[^>]*/?>", wb):
                nm, rid = _re.search(r'name="([^"]*)"', tag), _re.search(r'r:id="(rId\w+)"', tag)
                if nm and rid:
                    sheets.append((nm.group(1), rid.group(1)))
            default_sheets = [(nm, rid) for nm, rid in sheets if _os._DEFAULT_SHEET.match(nm.strip())]
            if len(default_sheets) >= 2:
                for nm, rid in default_sheets:
                    tgt = wb_rels.get(rid, "")
                    ws_path = "xl/" + tgt if tgt and not tgt.startswith("/") else tgt.lstrip("/")
                    content = sample(_os._read(zf, ws_path) or "")
                    if content:
                        targets.append((f"sheet:{nm}", f"default sheet tab “{nm}”", content))

            # 2.4.6b — default table columns ('Column1'); sample that column's own data.
            for name in zf.namelist():
                if not _re.fullmatch(r"xl/tables/table\d+\.xml", name):
                    continue
                txml = _os._read(zf, name) or ""
                disp = (_re.search(r'displayName="([^"]*)"', txml) or [None, "table"])[1] if _re.search(r'displayName="([^"]*)"', txml) else "table"
                ref = _re.search(r'\bref="([A-Z]+)\d+:([A-Z]+)\d+"', txml)
                start_col = ref.group(1) if ref else None
                cols = _re.findall(r'<tableColumn\b[^>]*\bname="([^"]*)"', txml)
                # the worksheet the table lives on: table rels → ../worksheets/sheetN.xml
                ws_for_table = ""
                for wsn in zf.namelist():
                    if _re.fullmatch(r"xl/worksheets/sheet\d+\.xml", wsn):
                        ws_for_table = ws_for_table or wsn        # best-effort: first sheet
                ws_xml = _os._read(zf, ws_for_table) or "" if ws_for_table else ""
                for i, cname in enumerate(cols):
                    if not _os._DEFAULT_COL.match(cname.strip()):
                        continue
                    col_letter = _col_add(start_col, i) if start_col else None
                    content = sample(ws_xml, col=col_letter) if col_letter else ""
                    targets.append((f"table:{disp}#col:{cname}", f"default column header “{cname}”",
                                    content or f"a column in table {disp}"))
    except Exception:
        return []
    if not targets:
        return []
    try:
        import ai as _ai
        # TEXT model — suggest_fix names each default tab / column below (_TEXT_GATE).
        if not _ai.model_is_available():
            return []
    except Exception:
        return []

    out: list[dict] = []
    for locator, before, content in targets[:_XLSX_LABEL_CAP]:
        try:
            res = _ai.suggest_fix("2.4.6", "Headings and Labels", "AA", "",
                                  detail=f"give a short descriptive label for this content: {content[:400]}",
                                  guidance=guidance)
        except Exception:
            res = None
        label = (res or {}).get("suggestion", "").strip().strip('"')
        if not label or len(label) > 60:
            continue
        out.append(proposal(
            locator=locator, before=before, proposed_value=label,
            rationale=f"AI named it from its own content — “{content[:110]}…” — confirm the label fits",
            source=f"AI text model ({(res or {}).get('model', 'llama')})"))
    return out


def _col_add(col: str, n: int) -> str:
    """Column letter n positions right of `col` (A + 2 → C)."""
    idx = 0
    for ch in col:
        idx = idx * 26 + (ord(ch) - 64)
    idx += n
    out = ""
    while idx > 0:
        idx, r = divmod(idx - 1, 26)
        out = chr(65 + r) + out
    return out


# ── docx 1.3.2 — floating-text reading-order recommendations ────────────────────
# The detector (office_structure DOCX_READING_ORDER_RISK) fires on text-bearing floating objects
# (DrawingML/VML text boxes, positioned frames): a screen reader reads them at their anchor point,
# not where they appear. There is NO safe silent fix — moving anchored content re-flows the page —
# so this is proposal-only: surface each floating box with its exact text and a concrete "place it
# inline here" recommendation for a human to apply. Deterministic (no model): the text and the
# recommendation come straight from the document, so it works with AI off.
_READING_ORDER_CAP = 12


def propose_reading_order(path, ext: str) -> list[dict]:
    """docx 1.3.2 Meaningful Sequence — one recommendation per text-bearing floating object,
    carrying the box's own text so a reviewer knows exactly what to move and can drop it into the
    body flow at the intended point. Gates on the detector's own condition (text-bearing text
    boxes / frames); [] for an ordinary linear document."""
    if (ext or "").lower().lstrip(".") != "docx":
        return []
    import zipfile

    import office_structure as _os
    try:
        with zipfile.ZipFile(path) as zf:
            doc = _os._read(zf, "word/document.xml") or ""
    except Exception:
        return []
    floats: list[str] = []
    for inner in _os._TXBX_CONTENT.findall(doc):
        txt = " ".join(t for t in _os._WT.findall(inner) if t.strip()).strip()
        if txt:
            floats.append(txt)
    for para in _os._PARA.findall(doc):
        if _os._FRAMEPR.search(para):
            txt = " ".join(t for t in _os._WT.findall(para) if t.strip()).strip()
            if txt:
                floats.append(txt)
    out: list[dict] = []
    for i, txt in enumerate(floats[:_READING_ORDER_CAP], 1):
        excerpt = txt if len(txt) <= 120 else txt[:117] + "…"
        out.append({**proposal(
            locator=f"floating-text:{i}",
            before="floating text box / frame — read at its anchor, not its visual position",
            proposed_value=f"Move this text into the body at its intended reading position: “{excerpt}”",
            rationale="a screen reader follows the document's linear order, so anchored text is spoken "
                      "out of sequence; placing it inline where it visually belongs fixes the order",
            source="floating text detected in the document (deterministic)"), "sc": "1.3.2"})
    return out


# ── One-click deterministic cards — layout/authoring calls a human elects ───────
# docx 1.4.8 (justified text → left-aligned) and pptx 1.4.2 (auto-starting audio → play on
# click). Both FIXES are deterministic, but applying them silently would change layout /
# authoring intent — so each becomes a one-click proposal: the exact change is pre-computed
# and stated, the human only elects it. Gates mirror the detectors exactly.


def propose_justified_fix(path, ext: str) -> list[dict]:
    """docx 1.4.8 — one card offering to set the document's justified paragraphs to
    left-aligned. Deterministic (no model); [] unless the detector's own condition holds
    (>= its justified-paragraph floor)."""
    if (ext or "").lower().lstrip(".") != "docx":
        return []
    import zipfile

    import office_structure as _os
    try:
        with zipfile.ZipFile(path) as zf:
            doc = _os._read(zf, "word/document.xml") or ""
    except Exception:
        return []
    justified = sum(1 for p in _os._PARA.findall(doc)
                    if _os._JC_BOTH.search(p) and "".join(_os._WT.findall(p)).strip())
    if justified < _os._MIN_JUSTIFIED_PARAS:
        return []
    return [proposal(
        locator=f"{justified} justified paragraph(s)",
        before='body text set justified (<w:jc w:val="both"/>) — uneven word spacing makes '
               "long text harder to read",
        proposed_value='Set the justified paragraphs to left-aligned (<w:jc w:val="left"/>)',
        rationale="The fix is exact and deterministic, but alignment is a layout decision — "
                  "confirm the document may be left-aligned",
        source="deterministic (detector-mirrored) — human election required")]


def propose_autoplay_fix(path, ext: str) -> list[dict]:
    """pptx 1.4.2 — one card per slide offering to make auto-starting embedded audio play
    on click instead. Deterministic (no model); mirrors pptx_audio_autoplay_checks."""
    if (ext or "").lower().lstrip(".") != "pptx":
        return []
    import office_structure as _os
    out: list[dict] = []
    for f in _os.pptx_audio_autoplay_checks(path):
        out.append(proposal(
            locator=(f.get("detail") or "slide")[:40],
            before="embedded audio starts automatically — no pause/stop control exists on a slide",
            proposed_value="Change the audio trigger from auto-start to play-on-click",
            rationale="The change is exact and deterministic, but when media plays is an "
                      "authoring decision — confirm click-to-play matches the deck's intent",
            source="deterministic (detector-mirrored) — human election required"))
    return out


# ── 1.1.1 Non-text Content — native-chart datasheet (deterministic, grounded) ───
# A native (DrawingML) chart in a docx/pptx/xlsx stores its OWN series data in chart XML.
# That is the strongest possible alt text: exact values, not a vision guess at a rendered
# picture. This proposer reads chart title + series names + categories + values straight
# from the XML and builds a grounded description + datasheet — the ADR-0016 gold standard
# (every number is the chart's own, nothing fabricated). Distinct from the images-of-text /
# vision proposers, which handle images WITHOUT recoverable data.
import re as _re

_C_SER = _re.compile(r"<c:ser\b.*?</c:ser>", _re.S)
_C_V = _re.compile(r"<c:v>([^<]*)</c:v>")
_C_TITLE = _re.compile(r"<c:title\b.*?</c:title>", _re.S)
_A_T_RE = _re.compile(r"<a:t>([^<]*)</a:t>")
_C_CHART_TYPE = _re.compile(r"<c:(bar|line|pie|scatter|area|doughnut|radar|bubble|surface|stock|ofPie)Chart\b")
_CHART_TYPE_NAME = {
    "bar": "Bar/column chart", "line": "Line chart", "pie": "Pie chart",
    "scatter": "Scatter chart", "area": "Area chart", "doughnut": "Doughnut chart",
    "radar": "Radar chart", "bubble": "Bubble chart", "surface": "Surface chart",
    "stock": "Stock chart", "ofPie": "Pie-of-pie chart",
}
_CHART_PART = _re.compile(r"(?:ppt|word|xl)/charts/chart\d+\.xml$")
_CHART_SERIES_CAP = 8       # bound a huge multi-series chart's datasheet
_CHART_CAT_CAP = 24


def _chart_block_values(block: str, tag: str) -> list[str]:
    """The <c:v> values inside the FIRST <c:tag>…</c:tag> sub-block of a series (cat/val/tx).
    The cached values (<c:*Cache>) are what a reader needs; formula refs are ignored."""
    m = _re.search(rf"<c:{tag}\b.*?</c:{tag}>", block, _re.S)
    return _C_V.findall(m.group(0)) if m else []


def _num(s: str) -> str:
    """Trim a chart's numeric string for display: '1.0'→'1', '1.50'→'1.5', leave text as-is."""
    try:
        f = float(s)
    except (TypeError, ValueError):
        return s
    return str(int(f)) if f == int(f) else f"{f:g}"


def _describe_chart(xml: str) -> dict | None:
    """Parse one chart XML into {title, type, series:[{name, values}], categories}. None when
    it carries no plottable series (empty/placeholder chart)."""
    sers = _C_SER.findall(xml)
    if not sers:
        return None
    tm = _C_TITLE.search(xml)
    title = " ".join(_A_T_RE.findall(tm.group(0))).strip() if tm else ""
    ctm = _C_CHART_TYPE.search(xml)
    ctype = _CHART_TYPE_NAME.get(ctm.group(1), "Chart") if ctm else "Chart"
    categories: list[str] = []
    series: list[dict] = []
    for block in sers[:_CHART_SERIES_CAP]:
        name = " ".join(_chart_block_values(block, "tx")).strip()
        values = _chart_block_values(block, "val")
        if not values:
            continue
        if not categories:
            categories = _chart_block_values(block, "cat")
        series.append({"name": name, "values": values})
    if not series:
        return None
    return {"title": title, "type": ctype, "series": series, "categories": categories}


def _describe_chart_via_chart_data(raw: bytes, entries: dict, part_name: str | None = None) -> dict | None:
    """Same {title, type, series, categories} shape, but parsed by chart_data's namespace-correct
    ElementTree reader instead of the `c:`-prefixed regexes above.

    Two chart flavours the regex parser above cannot see, both common in openpyxl-authored
    workbooks: (a) the chart part written in the DEFAULT chart namespace (`<ser>`, not `<c:ser>`),
    and (b) an xlsx chart that caches NO values at all — the numbers live in worksheet cells and
    only a `<c:f>` range is stored. chart_data resolves both (it reads the cells out of the
    package), so a workbook that would otherwise yield no chart proposal at all yields an exact,
    grounded one. Used as a fallback so the established parse — and its output — is untouched
    wherever it already works."""
    try:
        import chart_data
    except Exception:
        return None
    c = chart_data.parse_chart_part(raw, entries, part_name)
    if not c:
        return None
    series, categories = [], []
    for s in c.get("series", [])[:_CHART_SERIES_CAP]:
        pts = s.get("points") or []
        if not pts:
            continue
        if not categories:
            categories = [cat for cat, _ in pts]
        series.append({"name": s.get("name") or "", "values": [val for _, val in pts]})
    if not series:
        return None
    return {"title": c.get("title") or "", "type": c.get("type") or "Chart",
            "series": series, "categories": categories}


def _chart_alt_and_sheet(desc: dict) -> tuple[str, str]:
    """(concise alt text, full datasheet) from a parsed chart. Alt names what the chart shows
    and its range; the datasheet is the exact value table — both grounded in the chart's data."""
    title = desc["title"]
    names = [s["name"] for s in desc["series"] if s["name"]]
    named = f" comparing {', '.join(names)}" if names else ""
    cats = desc["categories"][:_CHART_CAT_CAP]
    span = f" across {cats[0]}–{cats[-1]}" if len(cats) >= 2 else ""
    titled = f" titled “{title}”" if title else ""
    alt = f"{desc['type']}{titled}{named}{span}.".strip()
    # Datasheet: one line per series, category:value pairs (the reader's real data alternative).
    lines: list[str] = []
    for s in desc["series"]:
        vals = s["values"][:_CHART_CAT_CAP]
        if cats and len(cats) == len(vals):
            pairs = ", ".join(f"{c} {_num(v)}" for c, v in zip(cats, vals))
        else:
            pairs = ", ".join(_num(v) for v in vals)
        lead = f"{s['name']}: " if s["name"] else ""
        lines.append(f"{lead}{pairs}")
    return alt, "\n".join(lines)


def propose_chart_datasheet(path, ext: str) -> list[dict]:
    """One 1.1.1 proposal per NATIVE chart in a docx/pptx/xlsx, carrying a deterministic,
    grounded description + the chart's exact data as a datasheet. Returns [] when the file
    has no native charts (embedded chart IMAGES are handled by the vision/OCR proposers).
    Never a fabricated value — every figure is read from the chart's own XML (ADR 0016)."""
    if (ext or "").lower().lstrip(".") not in ("docx", "pptx", "xlsx"):
        return []
    import zipfile
    out: list[dict] = []
    try:
        with zipfile.ZipFile(path) as zf:
            parts = sorted(n for n in zf.namelist() if _CHART_PART.search(n))
            entries = None
            for i, name in enumerate(parts):
                raw = zf.read(name)
                try:
                    desc = _describe_chart(raw.decode("utf-8", "ignore"))
                except Exception:
                    desc = None
                if not desc:                               # cell-referenced / default-namespace chart
                    if entries is None:                    # read the package once, only if needed
                        entries = {n: zf.read(n) for n in zf.namelist()}
                    desc = _describe_chart_via_chart_data(raw, entries, name)
                if not desc:
                    continue
                alt, sheet = _chart_alt_and_sheet(desc)
                out.append(proposal(
                    locator=f"chart {i + 1}" + (f" ({desc['title']})" if desc["title"] else ""),
                    before="a chart with no text alternative — assistive tech cannot convey its data",
                    proposed_value=alt,
                    rationale="Read directly from the chart's own data (no vision guess). "
                              "Data table:\n" + sheet,
                    source="chart data (deterministic — from the document's chart XML)"))
    except Exception:
        return []
    return out


# ── 1.3.1 / 2.4.6 Heading level inference (deterministic — from font-size rank) ─
def infer_heading_levels(sizes) -> dict:
    """Map a set of pseudo-heading font sizes → heading levels by descending rank: the
    largest distinct size is Heading 1, the next Heading 2, … clamped at Heading 6 (deeper
    ranks all collapse to 6, since WCAG only defines h1–h6). Deterministic: same sizes →
    same levels every run, so the inferred level is a High-confidence derivation, not a
    guess. `sizes` is any iterable of numbers (points/half-points — only the ORDER matters).

    Ranks by ABSOLUTE size across the whole document, so it has no defence against one
    outsized non-heading (a headline figure, a pull quote): that text takes Heading 1 and
    pushes every real section down a rank, and with >6 distinct sizes the sections collapse
    into Heading 6. Where the sizes arrive in DOCUMENT ORDER, prefer
    `heading_level_sequence` — it nests relative to what precedes each heading and cannot
    emit a skipped level."""
    distinct = sorted({float(s) for s in sizes if s is not None}, reverse=True)
    return {sz: min(i + 1, 6) for i, sz in enumerate(distinct)}


def heading_level_sequence(sizes) -> list[int]:
    """Map font sizes IN DOCUMENT ORDER → one heading level per size, as a sequence that
    never skips a level. Keeps a stack of the enclosing sizes: a size larger than the
    current one closes the levels it outranks (so the next sibling returns to its own
    depth), an equal size repeats the current depth, and a smaller size opens exactly one
    level deeper. The first heading is therefore always Heading 1 and every step down is
    +1 — the monotonic sequence WCAG expects — whatever the absolute point sizes are.

    This is what makes the derivation trustworthy where `infer_heading_levels` is not: the
    level of a heading depends on the headings around it, not on whether some unrelated
    line in the document happens to be set larger. Deterministic — same sizes in the same
    order → the same levels every run. Depth is clamped at 6 (WCAG defines h1–h6 only)
    while the stack keeps its true depth, so closing back out lands on the right level."""
    stack: list[float] = []
    out: list[int] = []
    for s in sizes:
        if s is None:                       # unknown size — hold the current depth
            out.append(min(max(len(stack), 1), 6))
            continue
        sz = float(s)
        while stack and stack[-1] < sz:
            stack.pop()
        if not stack or stack[-1] != sz:
            stack.append(sz)
        out.append(min(len(stack), 6))
    return out


def propose_underline_restore(path, ext: str) -> list[dict]:
    """docx 1.4.1 — one card offering to put the underline back on hyperlinks that had it
    explicitly removed. Deterministic (no model); mirrors the detector's own condition.

    WHY THIS CRITERION GETS A PREFILLED CARD AT ALL. 1.4.1 in general is editorial: choosing how
    a document should signal meaning without relying on colour is the author's decision, and
    nothing can guess it. But the SIGNAL ACP detects is narrower than the criterion — it is
    specifically `<w:u w:val="none"/>` on a hyperlink, i.e. the underline was deliberately taken
    off, leaving colour alone to mark the link. For that signal the canonical remedy is exact,
    named by WCAG's own technique, and needs no judgement: put the underline back.

    So the card states one change rather than asking a question. A reviewer who has another
    non-colour cue in mind (a leading icon, bold weight, a "(link)" suffix) declines it — which
    is why this is an election and not an automatic write.
    """
    if (ext or "").lower().lstrip(".") != "docx":
        return []
    import zipfile

    import office_structure as _os
    try:
        with zipfile.ZipFile(path) as zf:
            doc = _os._read(zf, "word/document.xml") or ""
    except Exception:
        return []
    n = sum(1 for _rid, inner in _os._HYPERLINK.findall(doc) if _os._W_U_NONE.search(inner))
    if not n:
        return []
    return [proposal(
        locator=f"{n} hyperlink(s) with the underline removed",
        before='hyperlinks carry <w:u w:val="none"/> — with the underline gone, colour is the '
               "only thing marking them as links, which fails for a reader who cannot "
               "distinguish that colour",
        proposed_value='Restore the underline on those hyperlinks (remove <w:u w:val="none"/>)',
        rationale="The underline is WCAG's own worked example of a non-colour cue for links, and "
                  "restoring it is exact — but any other non-colour cue also satisfies 1.4.1, so "
                  "decline this if the document marks links some other way",
        source="deterministic (detector-mirrored) — human election required",
        sc="1.4.1")]


def _outline_reaching_3to1(border_hex: str, fill_hex: str) -> str | None:
    """The nearest shade of `border_hex` that reaches 3:1 against `fill_hex`, or None.

    Walks the outline toward black and toward white in parallel and takes whichever arrives
    first, so the suggestion stays as close to the author's chosen colour as the threshold
    allows — a card that proposed pure black on every faint outline would be correct and
    ignored.

    Returns None only on malformed input. The SEARCH cannot fail: for every fill, either black
    or white clears 3:1 — checked exhaustively over the greyscale range, and it follows from the
    formula, since both failing would need the fill's luminance to be simultaneously below 0.10
    and above 0.30. An earlier version of this docstring claimed mid-tone fills could defeat it;
    a test written to prove that claim failed, and the claim was wrong rather than the code.
    """
    import office_structure as _os
    try:
        r, g, b = (int(border_hex[i:i + 2], 16) for i in (0, 2, 4))
    except (ValueError, IndexError):
        return None
    for step in range(1, 256):
        for cand in ((max(0, r - step), max(0, g - step), max(0, b - step)),
                     (min(255, r + step), min(255, g + step), min(255, b + step))):
            hexed = "%02X%02X%02X" % cand
            if _os._contrast_ratio(hexed, fill_hex) >= 3.0:
                return hexed
    return None


def propose_outline_contrast(path, ext: str) -> list[dict]:
    """docx 1.4.11 — one card naming the shade that would bring a faint shape outline to 3:1.

    THE MEASUREMENT TRAVELS WITH THE CARD, and that is the point of this proposer. The detector
    already computed the ratio and knows the target; without carrying them, a reviewer opens the
    document, finds the shape, samples two colours and recomputes a number ACP had. The card
    states the measured ratio, the 3:1 it needed, and a specific colour that would reach it.

    An ELECTION, not a write. Whether the outline may change at all is a question about the
    document's visual design, and a faint outline that is purely decorative needs no fix — which
    is the other thing only a human can settle.
    """
    if (ext or "").lower().lstrip(".") != "docx":
        return []
    import re as _re

    import office_structure as _os
    found = _os.docx_nontext_contrast_checks(path)
    if not found:
        return []
    f = found[0]
    ratio = (f.get("evidence") or {}).get("value")
    m = _re.search(r"outline #([0-9A-Fa-f]{6}) on its #([0-9A-Fa-f]{6}) fill", f.get("detail", ""))
    if not m:
        return []
    border_hex, fill_hex = m.group(1).upper(), m.group(2).upper()
    suggestion = _outline_reaching_3to1(border_hex, fill_hex)
    if not suggestion:
        return []
    return [proposal(
        locator=f"shape outline #{border_hex} on #{fill_hex}",
        before=f"the outline is {ratio}:1 against its own fill, below the 3:1 WCAG requires for "
               "a shape boundary that carries meaning",
        proposed_value=f"Change the outline to #{suggestion} "
                       f"({_os._contrast_ratio(suggestion, fill_hex):.1f}:1 against the same fill)",
        rationale="The colour above is the nearest shade of your own outline colour that reaches "
                  "3:1 — but if the shape is decorative rather than meaningful, no change is "
                  "needed and this card should be declined",
        source="deterministic (measured) — human election required",
        sc="1.4.11")]
