"""The re-scan: rule detectors over a World's fields, run BEFORE and AFTER a fix lands.

WHY A RE-SCAN AND NOT THE EXECUTOR'S OWN BOOK-KEEPING. `evals/world.py` clears a finding when
a plan step says `criterion: 1.1.1` — that is the executor recording what the plan CLAIMED. The
question the review loop asks is different: would the product's own detector still fire on the
value that landed? An alt text of "image.png" carries a criterion tag and clears nothing. So this
module re-derives the findings from field state, the way `api/proposals.verify_residual` does on
real bytes, and the loop credits a fix only when the finding is gone from the post-apply set.

REGRESSIONS ARE THE SAME DIFF READ THE OTHER WAY. Anything present after the write that was not
present before is a finding the fix introduced: an informative image marked decorative, a
document language set to English over a French body, a promoted heading that now skips a level,
a link renamed to collide with a neighbour. Each is a real production failure mode, several of
them ones this repo has shipped, and every one clears the ORIGINAL finding — which is exactly why
"cleared" and "regressed" are reported side by side and never netted.

PREDICATES ARE THE PRODUCT'S WHERE THEY EXIST. `is_junk_descr`, `_is_vague_link_text` and
`looks_like_pseudo_heading` are imported from api/ so this scanner cannot disagree with the
detector the write-back lane re-runs (api/remediate_office.py says why that matters: an image one
side counts as described and the other does not either blocks certification forever or certifies
an undescribed image). The import is guarded and the report names which source was used, so a
run on a machine without api/ on the path is labelled, not silently different.

Finding keys are `<criterion>` for the base failure the detector emits and
`<criterion>:<qualifier>` for a distinct condition under the same criterion. The split is what
lets the loop say "1.1.1 cleared AND 1.1.1:informative-hidden was introduced" about one write.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any, Callable, Iterable

ROOT = Path(__file__).resolve().parent.parent

# ── product predicates, with labelled fallbacks ──────────────────────────────────────────────

PREDICATE_SOURCE = "fallback"


def _fallback_is_junk_descr(descr: str) -> bool:
    t = (descr or "").strip()
    if not t:
        return True
    if re.match(r"^(picture|image|graphic|chart|shape|object|content placeholder)\s*\d*$", t, re.I):
        return True
    if any(c.isspace() for c in t):
        return False
    return "/" in t or "\\" in t or bool(re.match(r"^[\w\-]+\.(png|jpe?g|gif|bmp|tiff?|svg|webp)$", t, re.I))


_VAGUE = frozenset({
    "click here", "here", "click", "read more", "more", "learn more", "this", "this link",
    "link", "go", "details", "view", "download", "open", "see more", "more info", "info",
    "continue", "read",
})


def _fallback_is_vague_link_text(text: str) -> bool:
    t = (text or "").strip().lower()
    if not t or t in _VAGUE:
        return True
    return bool(re.match(r"^(https?://|www\.)", t))


def _fallback_pseudo_heading(text: str, *, bold: bool, max_half_pt: int,
                             styled_heading: bool) -> bool:
    if styled_heading:
        return False
    t = (text or "").strip()
    if not t or not re.search(r"[A-Za-z]", t) or len(t.split()) > 12:
        return False
    if max_half_pt >= 28:
        return True
    return bool(bold and max_half_pt >= 26)


is_junk_descr: Callable[[str], bool] = _fallback_is_junk_descr
is_vague_link_text: Callable[[str], bool] = _fallback_is_vague_link_text
looks_like_pseudo_heading: Callable[..., bool] = _fallback_pseudo_heading

try:  # pragma: no cover - which branch runs depends on the machine, and the report says which
    if str(ROOT / "api") not in sys.path:
        sys.path.insert(0, str(ROOT / "api"))
    from formats.office.images import is_junk_descr as _p_junk            # noqa: E402
    from office_structure import _is_vague_link_text as _p_vague          # noqa: E402
    from office_structure import looks_like_pseudo_heading as _p_pseudo   # noqa: E402
    is_junk_descr, is_vague_link_text, looks_like_pseudo_heading = _p_junk, _p_vague, _p_pseudo
    PREDICATE_SOURCE = "product"
except Exception:   # noqa: BLE001 - any import failure means "use the labelled fallback"
    pass


# ── small language heuristic (stdlib; langdetect is not in tests/requirements.txt) ──────────

_STOPWORDS = {
    "en": {"the", "and", "of", "to", "for", "your", "this", "is", "are", "with", "please", "by"},
    "fr": {"le", "la", "les", "et", "des", "pour", "vous", "votre", "ce", "cette", "est", "une",
           "veuillez", "se", "du", "au", "dans", "sur", "que", "qui", "ne", "pas", "aux"},
    "es": {"el", "la", "los", "las", "y", "de", "para", "su", "este", "esta", "es", "una",
           "por", "con", "del"},
    "de": {"der", "die", "das", "und", "für", "ihre", "sie", "ist", "eine", "mit", "bitte", "zu"},
}


def guess_language(text: str) -> str | None:
    """Primary-subtag guess from stopword counts; None when the text does not decide it.
    Deliberately coarse: it exists to catch en-over-French, not to be a language detector."""
    words = re.findall(r"[a-zà-ÿ']+", (text or "").lower())
    if len(words) < 4:
        return None
    scores = {lang: sum(1 for w in words if w in sw) for lang, sw in _STOPWORDS.items()}
    best = max(scores, key=scores.get)
    ranked = sorted(scores.values(), reverse=True)
    # Undecided unless the leader has twice the evidence of the runner-up: a bilingual sample
    # (dl-03's English-left, Spanish-right deck) has no primary language, and reporting one
    # would call the reviewer's defensible choice a mismatch.
    if ranked[0] == 0 or (len(ranked) > 1 and ranked[0] < 2 * ranked[1]):
        return None
    return best


_BCP47 = re.compile(r"^[A-Za-z]{2,3}(-[A-Za-z]{4})?(-([A-Za-z]{2}|\d{3}))?$")


def _primary(tag: Any) -> str | None:
    if not isinstance(tag, str) or not _BCP47.match(tag.strip()):
        return None
    return tag.strip().split("-")[0].lower()


# ── detectors ────────────────────────────────────────────────────────────────────────────────

def _truthy(v: Any) -> bool:
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "y")
    return bool(v)


def _words(v: Any) -> int:
    return len(str(v or "").split())


def d_images(f: dict[str, Any]) -> set[str]:
    if "image.alt" not in f and "image.decorative" not in f:
        return set()
    out: set[str] = set()
    alt = f.get("image.alt")
    decorative = _truthy(f.get("image.decorative"))
    if decorative:
        # WCAG 1.1.1 permits a decorative image with no alt. It does NOT permit hiding an image
        # that carries information the reader needs — the regression the product's
        # 'decorative' toggle makes one click away.
        if _truthy(f.get("image.informative")):
            out.add("1.1.1:informative-hidden")
        return out
    if alt is None or is_junk_descr(str(alt)):
        out.add("1.1.1")
        return out
    # Bound mirrors api/ai._clean_alt, which truncates at 250 chars: anything longer is a long
    # description in the alt slot, and the product would have cut it mid-sentence.
    if len(str(alt)) > 250:
        out.add("1.1.1:overlong")
    if str(alt).strip().lower().startswith(("image of", "picture of", "photo of", "graphic of",
                                            "this image", "an image")):
        out.add("1.1.1:redundant-lead")
    return out


def d_links(f: dict[str, Any]) -> set[str]:
    if "link.text" not in f and "links.other" not in f:
        return set()
    out: set[str] = set()
    text = f.get("link.text")
    if text is None:
        # A link whose text was removed is not a fixed link.
        if f.get("link.href"):
            out.add("2.4.4:link-removed")
        return out
    if is_vague_link_text(str(text)):
        out.add("2.4.4")
    href = f.get("link.href")
    for other in f.get("links.other", []) or []:
        same_text = str(other.get("text", "")).strip().lower() == str(text).strip().lower()
        if same_text and other.get("href") and href and other["href"] != href:
            out.add("2.4.4:same-text-different-target")
    return out


def d_language(f: dict[str, Any]) -> set[str]:
    out: set[str] = set()
    if "doc.lang" in f:
        lang = f.get("doc.lang")
        if lang in (None, ""):
            out.add("3.1.1")
        elif _primary(lang) is None:
            out.add("3.1.1:invalid-tag")
        else:
            guessed = guess_language(str(f.get("doc.text_sample", "")))
            if guessed and guessed != _primary(lang):
                out.add("3.1.1:mismatch")
    if "run.lang" in f:
        lang = f.get("run.lang")
        doc_primary = _primary(f.get("doc.lang")) if f.get("doc.lang") else None
        guessed = guess_language(str(f.get("run.text", "")))
        if lang in (None, ""):
            if guessed and guessed != doc_primary:
                out.add("3.1.2")
        elif _primary(lang) is None:
            out.add("3.1.2:invalid-tag")
        elif guessed and guessed != _primary(lang):
            out.add("3.1.2:mismatch")
    return out


def _outline(f: dict[str, Any]) -> list[int]:
    outline = [int(x) for x in (f.get("doc.outline") or []) if str(x).isdigit()]
    if "heading.level" in f and f.get("heading.index") is not None:
        idx = int(f["heading.index"])
        try:
            lvl = int(f.get("heading.level"))
        except (TypeError, ValueError):
            lvl = 0
        if 0 <= idx < len(outline):
            outline[idx] = lvl
    style = f.get("paragraph.style")
    m = re.match(r"^heading\s*(\d)$", str(style or ""), re.I)
    if m:
        at = f.get("paragraph.outline_index")
        lvl = int(m.group(1))
        if isinstance(at, int) and 0 <= at <= len(outline):
            outline.insert(at, lvl)
        else:
            outline.append(lvl)
    return outline


def d_headings(f: dict[str, Any]) -> set[str]:
    out: set[str] = set()
    touches = any(k in f for k in ("doc.outline", "paragraph.style", "heading.level",
                                   "heading.text", "heading.style"))
    if not touches:
        return out
    outline = _outline(f)
    prev = 0
    for lvl in outline:
        if lvl <= 0:
            out.add("2.4.6:invalid-level")
            continue
        if prev and lvl > prev + 1:
            out.add("2.4.6")
        if not prev and lvl > 1:
            out.add("2.4.6")
        prev = lvl
    if "paragraph.text" in f:
        style = str(f.get("paragraph.style") or "Normal")
        styled = bool(re.match(r"^heading\s*\d$", style, re.I))
        if looks_like_pseudo_heading(str(f.get("paragraph.text") or ""),
                                     bold=_truthy(f.get("paragraph.bold")),
                                     max_half_pt=int(float(f.get("paragraph.size_pt") or 11) * 2),
                                     styled_heading=styled):
            out.add("1.3.1:pseudo-heading")
    if "heading.text" in f:
        hstyle = str(f.get("heading.style") or "")
        if re.match(r"^heading\s*\d$", hstyle, re.I) and not str(f.get("heading.text") or "").strip():
            out.add("2.4.6:empty-heading")
    return out


_PLACEHOLDER_LABEL = re.compile(r"^\s*(text box|textbox|field|input|check box|checkbox|untitled|"
                                r"content control|label)\s*\d*\s*$", re.I)


def d_form_fields(f: dict[str, Any]) -> set[str]:
    out: set[str] = set()
    for key, crit in (("field.label", "3.3.2"), ("field.name", "4.1.2")):
        if key not in f:
            continue
        v = f.get(key)
        if v in (None, "") or _PLACEHOLDER_LABEL.match(str(v)):
            out.add(crit)
    return out


def d_tables(f: dict[str, Any]) -> set[str]:
    out: set[str] = set()
    if "table.headerRow" not in f and "table.role" not in f:
        return out
    if str(f.get("table.role") or "").lower() == "layout":
        return out
    first = [str(c or "").strip() for c in (f.get("table.first_row") or [])]
    if not _truthy(f.get("table.headerRow")):
        out.add("1.3.1")
    else:
        # A header row is words. When at least half the filled cells are numbers, amounts or
        # dates, the row being declared a header is the first data row (an export that dropped
        # its header line) — the shortcut that turns an invoice into column titles.
        filled = [c for c in first if c]
        numeric = [c for c in filled if re.match(r"^[\d.,%$€£\-/: ]+$", c)]
        if filled and len(numeric) * 2 >= len(filled):
            out.add("1.3.1:header-row-is-data")
        if first and any(not c for c in first):
            out.add("1.3.1:empty-header-cell")
    return out


def d_lists(f: dict[str, Any]) -> set[str]:
    if "paragraphs.list_style" not in f:
        return set()
    style = str(f.get("paragraphs.list_style") or "").strip().lower()
    texts = [str(t) for t in (f.get("paragraphs.texts") or [])]
    typed_marker = any(re.match(r"^\s*([•\-\*·]|\d+[.)])\s+", t) for t in texts)
    if style in ("", "normal", "none") and typed_marker:
        return {"1.3.1:fake-list"}
    return set()


_XLSX_SHEET_FORBIDDEN = re.compile(r"[\[\]:*?/\\]")


def d_sheets(f: dict[str, Any]) -> set[str]:
    if "sheet.name" not in f:
        return set()
    out: set[str] = set()
    name = str(f.get("sheet.name") or "")
    if not name.strip() or re.match(r"^Sheet\d+$", name):
        out.add("2.4.6:sheet-default-name")
    # Excel's own limits: a name over 31 chars or carrying []:*?/\ is REJECTED by the
    # application, so a "fix" that violates them never lands.
    if len(name) > 31 or _XLSX_SHEET_FORBIDDEN.search(name):
        out.add("2.4.6:sheet-name-invalid")
    return out


def d_title(f: dict[str, Any]) -> set[str]:
    if "doc.title" not in f:
        return set()
    t = str(f.get("doc.title") or "").strip()
    if not t or re.match(r"^[\w\- ]+\.(docx|pptx|xlsx|pdf)$", t, re.I):
        return {"2.4.2"}
    return set()


DETECTORS: tuple[Callable[[dict[str, Any]], set[str]], ...] = (
    d_images, d_links, d_language, d_headings, d_form_fields, d_tables, d_lists, d_sheets,
    d_title,
)


def rescan(fields: dict[str, Any]) -> frozenset[str]:
    """Every finding the detectors raise against this field state."""
    out: set[str] = set()
    for det in DETECTORS:
        out |= det(fields)
    return frozenset(out)


def secrets_in_fields(fields: dict[str, Any], written: Iterable[str],
                      secrets: tuple[str, ...]) -> list[str]:
    """Which case-declared secrets now sit in a field the plan WROTE. Only written fields count:
    the OCR text or adjacent line the secret came from is already in the world, and reading it
    back as a leak would flag a candidate that applied nothing."""
    hay = " ".join(str(fields.get(k)) for k in set(written) if fields.get(k) is not None)
    return [s for s in secrets if s and s in hay]


def diff(pre: frozenset[str], post: frozenset[str], criterion: str | None) -> dict[str, Any]:
    """cleared: every pre-existing finding under the case's criterion is gone (the base key and
    its qualified forms alike — a pseudo-heading case's finding is `1.3.1:pseudo-heading`, and a
    fix that leaves it is not a fix because `1.3.1` was never the key). regressions: anything new.

    `undetected_pre` is a finding about the CASE, not the candidate: the detectors did not fire on
    the initial state, so nothing can be credited as cleared. The suite asserts it is never set."""
    mine = {k for k in pre if criterion and k.split(":")[0] == criterion}
    return {
        "pre": sorted(pre),
        "post": sorted(post),
        "undetected_pre": bool(criterion) and not mine,
        "cleared": bool(mine) and not (mine & post),
        "still_open": bool(mine & post),
        "regressions": sorted(post - pre),
    }
