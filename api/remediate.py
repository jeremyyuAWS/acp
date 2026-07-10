"""Server-side HTML remediation engine (ADR 0005).

Mirrors the frontend rule contract (frontend/src/rules/*.js) on the backend so
remediation can run async/durably in a worker (ADR 0004 `remediate_file` jobs),
not just in the browser. Each fixer is a deterministic transform over an lxml tree.

Apply policy (matches the AI toggle / deterministic-only mode):
  - 'auto'        fixers are applied always.
  - 'ai-assisted' / 'human-only' findings are NOT auto-fixed — their rule ids are
    returned as 'deferred' so the caller routes them to the HITL queue.

To add a fixer: write fix_<sc>(tree) -> list[str] and register it in FIXERS with
its fix_mode, citing the frontend module it mirrors. Keep the two in sync (parity).
"""
from __future__ import annotations
import re
from typing import Callable

from lxml import html as _lh

# wcag_sc -> (fix_mode, fixer). fixer(tree) mutates tree, returns change descriptions.
Fixer = Callable[..., list]
FIXERS: dict[str, tuple[str, Fixer]] = {}


def _rec(diffs, rule_id: str, before: str, after: str, note: str = "") -> None:
    """Append one before→after record for the certification report. No-op when the
    caller passed no collector, so the return contract stays a plain list[str]."""
    if diffs is not None:
        diffs.append({"rule_id": rule_id, "before": before, "after": after, "note": note})


def _register(sc: str, fix_mode: str):
    def _wrap(fn):
        FIXERS[sc] = (fix_mode, fn)
        return fn
    return _wrap


# ── 3.1.1 Language of Page (auto) — mirrors frontend/src/rules/wcag-3-1-1.js ──
@_register("3.1.1", "auto")
def _fix_lang(tree, diffs=None) -> list:
    root = tree if tree.tag == "html" else (tree.getroottree().getroot())
    html_el = root if root.tag == "html" else root.find(".//html")
    if html_el is None:
        html_el = root
    if not (html_el.get("lang") or "").strip():
        html_el.set("lang", "en")
        _rec(diffs, "3.1.1", "<html> (no lang attribute)", '<html lang="en">',
             "so assistive tech announces the page in the right language")
        return ["Set document language to English · 3.1.1"]
    return []


# ── 2.4.2 Page Titled (auto) — mirrors frontend/src/rules/wcag-2-4-2.js ──
@_register("2.4.2", "auto")
def _fix_title(tree, diffs=None) -> list:
    titles = tree.xpath("//title")
    title = titles[0] if titles else None
    if title is not None and (title.text or "").strip():
        return []
    heads = tree.xpath("//head")
    if title is None:
        from lxml.etree import SubElement
        parent = heads[0] if heads else tree.xpath("//html")[0] if tree.xpath("//html") else tree
        title = SubElement(parent, "title")
    h1 = tree.xpath("//h1")
    text = (h1[0].text_content().strip() if h1 else "") or "Document"
    title.text = text[:80]
    _rec(diffs, "2.4.2", "(no <title> — the page could not be identified in a tab or history)",
         title.text, "descriptive title derived from the page's <h1>")
    return ["Added a descriptive page title · 2.4.2"]


# ── 1.3.1 Info and Relationships — form labels (auto) ──
# Mirrors frontend/src/rules/wcag-1-3-1.js: give unlabeled controls an aria-label
# from a deterministic hint (placeholder → name → "Field").
@_register("1.3.1", "auto")
def _fix_form_labels(tree, diffs=None) -> list:
    changed = False
    for inp in tree.xpath("//input | //select | //textarea"):
        cid = inp.get("id")
        labelled = (
            inp.get("aria-label")
            or inp.get("aria-labelledby")
            or (cid and tree.xpath(f'//label[@for="{cid}"]'))
        )
        if labelled:
            continue
        hint = (inp.get("placeholder") or inp.get("name") or "Field").strip()[:60]
        inp.set("aria-label", hint or "Field")
        _rec(diffs, "1.3.1", f"<{inp.tag}> control with no label",
             f'aria-label="{hint or "Field"}"', "so a screen reader announces the field's purpose")
        changed = True
    return ["Labeled form controls · 1.3.1"] if changed else []


# ── 1.4.3 / 1.4.6 Contrast — darken low-contrast inline text colour (auto) ──
# Mirrors the scanner's inline-colour heuristic (text colour luma > 0.45 fails the
# enhanced ratio on a light background). Darkens the flagged colour so BOTH AA and
# AAA clear; skips any element with a dark inline background — there darkening would
# make it worse, so it's left for human review.
_C_COLOR = re.compile(r"(?:^|[^-])color:\s*#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})\b")
_C_BG = re.compile(r"background(?:-color)?:\s*#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})\b")


def _c_luma(h: str) -> float:
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255


@_register("1.4.3", "auto")
def _fix_contrast(tree, diffs=None) -> list:
    n = 0
    for el in tree.iter():
        style = el.get("style") if hasattr(el, "get") else None
        if not style:
            continue
        m = _C_COLOR.search(style)
        if not m or _c_luma(m.group(1)) <= 0.45:
            continue
        bg = _C_BG.search(style)
        if bg and _c_luma(bg.group(1)) < 0.5:      # dark background → darkening would be wrong
            continue
        el.set("style", re.sub(r"((?:^|[^-])color:\s*)#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})\b",
                               lambda mm: mm.group(1) + "#111111", style, count=1))
        text = (el.text or "").strip()
        _rec(diffs, "1.4.3", f"color:#{m.group(1)} (too light on a light background — fails AA)",
             "color:#111111 (passes AA and AAA)",
             f'text "{text[:40]}"' if text else "low-contrast inline text")
        n += 1
    return [f"Darkened {n} low-contrast inline text colour(s) to meet AA/AAA · 1.4.3 / 1.4.6"] if n else []


# ── 1.4.10 Reflow — inject a responsive viewport (auto) ──
# Mirrors scanner: a real page (has meta/link/style) with no viewport meta fails
# reflow. Add a zoom-friendly viewport (no user-scalable=no, so it can't create a
# 1.4.4 issue). Creates <head> if the document lacks one.
def _head(tree):
    heads = tree.xpath("//head")
    if heads:
        return heads[0]
    htmls = tree.xpath("//html")
    parent = htmls[0] if htmls else tree
    head = parent.makeelement("head", {})
    parent.insert(0, head)
    return head


@_register("1.4.10", "auto")
def _fix_reflow(tree, diffs=None) -> list:
    has_head_content = any(tree.xpath(f"//{t}") for t in ("meta", "link", "style"))
    has_viewport = any((m.get("name") or "").lower() == "viewport" for m in tree.iter("meta"))
    if not has_head_content or has_viewport:
        return []
    head = _head(tree)
    head.insert(0, head.makeelement("meta", {"name": "viewport", "content": "width=device-width, initial-scale=1"}))
    _rec(diffs, "1.4.10", "(no viewport meta — content scrolled in two directions at 320px)",
         '<meta name="viewport" content="width=device-width, initial-scale=1">',
         "so content reflows to a single column")
    return ["Added a responsive viewport so content reflows without horizontal scroll · 1.4.10"]


# ── 1.4.4 Resize Text — un-block pinch-zoom on the viewport (auto) ──
@_register("1.4.4", "auto")
def _fix_resize(tree, diffs=None) -> list:
    n = 0
    for m in tree.iter("meta"):
        if (m.get("name") or "").lower() != "viewport":
            continue
        content = m.get("content") or ""
        if re.search(r"user-scalable\s*=\s*(no|0)|maximum-scale\s*=\s*(0|1)(\.0+)?\b", content, re.I):
            m.set("content", "width=device-width, initial-scale=1")
            _rec(diffs, "1.4.4", f'viewport "{content[:60]}" (pinch-zoom blocked)',
                 "width=device-width, initial-scale=1", "so text can be zoomed to 200%+")
            n += 1
    return [f"Restored pinch-zoom / text resize on {n} viewport tag(s) · 1.4.4"] if n else []


# ── 1.4.12 Text Spacing — relax fixed-pixel line-height (auto) ──
@_register("1.4.12", "auto")
def _fix_text_spacing(tree, diffs=None) -> list:
    n = 0
    for el in tree.iter():
        style = el.get("style") if hasattr(el, "get") else None
        if not style or not (lh := re.search(r"line-height:\s*\d+px", style, re.I)):
            continue
        el.set("style", re.sub(r"line-height:\s*\d+px", "line-height:1.5", style, flags=re.I))
        _rec(diffs, "1.4.12", f"{lh.group(0)} (clips when users override text spacing)",
             "line-height:1.5", "so overridden spacing no longer clips text")
        n += 1
    return [f"Relaxed fixed line-height on {n} element(s) so users can override spacing · 1.4.12"] if n else []


# ── 1.4.2 Audio Control — stop autoplaying media (auto) ──
@_register("1.4.2", "auto")
def _fix_autoplay(tree, diffs=None) -> list:
    n = 0
    for m in tree.iter("audio", "video"):
        if m.get("autoplay") is not None and m.get("controls") is None:
            m.attrib.pop("autoplay", None)
            _rec(diffs, "1.4.2", f"<{m.tag} autoplay> with no controls (audio a user can't stop)",
                 f"<{m.tag}> (autoplay removed)", "so the sound no longer plays automatically")
            n += 1
    return [f"Removed autoplay from {n} media element(s) · 1.4.2"] if n else []


# ── 1.3.4 Orientation — un-lock content hidden in one orientation (auto) ──
_ORIENT = re.compile(
    r"@media[^{]*\(\s*orientation\s*:\s*(?:portrait|landscape)\s*\)[^{]*\{[^@]*?display\s*:\s*none", re.I)


@_register("1.3.4", "auto")
def _fix_orientation(tree, diffs=None) -> list:
    n = 0
    for st in tree.iter("style"):
        txt = st.text or ""
        if txt and _ORIENT.search(txt):
            st.text = _ORIENT.sub(lambda mm: re.sub(r"display\s*:\s*none", "display:revert", mm.group(0), count=1, flags=re.I), txt)
            _rec(diffs, "1.3.4", "@media (orientation) { … display:none } hid content in one orientation",
                 "display:revert", "so content shows in both portrait and landscape")
            n += 1
    return [f"Removed orientation lock from {n} stylesheet(s) · 1.3.4"] if n else []


# ── 1.3.5 Identify Input Purpose — declare autocomplete tokens (auto) ──
# Mirrors frontend/src/rules/wcag-1-3-5.js and scanner.py's HTML_INPUT_NO_AUTOCOMPLETE
# predicate: the token keyword set is kept identical to scanner._INPUT_PURPOSE so
# every field the scanner flags gets a token here and re-scans clean.
_PURPOSES = [
    (re.compile(r"e-?mail", re.I), "email"),
    (re.compile(r"(^|[\s_-])(tel|phone|mobile)([\s_-]|$)", re.I), "tel"),
    (re.compile(r"(first|given)[-_ ]?name", re.I), "given-name"),
    (re.compile(r"(last|family|sur)[-_ ]?name", re.I), "family-name"),
    (re.compile(r"full[-_ ]?name|^name$", re.I), "name"),
    (re.compile(r"(^|[\s_-])(zip|postal)([-_ ]?code)?([\s_-]|$)", re.I), "postal-code"),
    (re.compile(r"(^|[\s_-])country([\s_-]|$)", re.I), "country-name"),
    (re.compile(r"(^|[\s_-])(city|town)([\s_-]|$)", re.I), "address-level2"),
    (re.compile(r"street|address", re.I), "street-address"),
    (re.compile(r"(^|[\s_-])(org|organization|company)([\s_-]|$)", re.I), "organization"),
    (re.compile(r"birth[-_ ]?(date|day)|(^|[\s_-])dob([\s_-]|$)", re.I), "bday"),
]


def _purpose_of(inp) -> str | None:
    t = (inp.get("type") or "").lower()
    if t == "email":
        return "email"
    if t == "tel":
        return "tel"
    hint = f'{inp.get("name") or ""} {inp.get("id") or ""} {inp.get("placeholder") or ""}'
    for rx, token in _PURPOSES:
        if rx.search(hint):
            return token
    return None


@_register("1.3.5", "auto")
def _fix_input_purpose(tree, diffs=None) -> list:
    n = 0
    for inp in tree.iter("input"):
        if (inp.get("autocomplete") or "").strip():
            continue
        token = _purpose_of(inp)
        if token:
            inp.set("autocomplete", token)
            n += 1
    return [f"Declared input purposes with autocomplete tokens on {n} field(s) · 1.3.5"] if n else []


# ── 1.4.1 Use of Color — underline links styled by colour alone (auto) ──
# Mirrors frontend/src/rules/wcag-1-4-1.js and scanner.py's HTML_LINK_COLOR_ONLY.
@_register("1.4.1", "auto")
def _fix_use_of_color(tree, diffs=None) -> list:
    n = 0
    for a in tree.iter("a"):
        s = a.get("style") or ""
        if not s or not re.search(r"(?:^|;)\s*color\s*:", s):
            continue
        if re.search(r"text-decoration\s*:[^;]*underline", s, re.I):
            continue
        if re.search(r"text-decoration\s*:", s, re.I):
            s = re.sub(r"text-decoration\s*:[^;]*", "text-decoration:underline", s, count=1, flags=re.I)
        else:
            s = re.sub(r";?\s*$", "; ", s) + "text-decoration:underline"
        a.set("style", s)
        n += 1
    return [f"Underlined {n} link(s) distinguished by colour alone · 1.4.1"] if n else []


# ── 2.4.1 Bypass Blocks — inject a skip link + main landmark (auto) ──
# Mirrors frontend/src/rules/wcag-2-4-1.js and scanner.py's HTML_NO_SKIP_LINK: only
# a document that HAS repeated chrome (nav/header) and NO existing bypass is touched.
def _role(el) -> str:
    return (el.get("role") or "") if hasattr(el, "get") else ""


@_register("2.4.1", "auto")
def _fix_bypass_blocks(tree, diffs=None) -> list:
    body = tree.find(".//body")
    if body is None:
        return []
    has_chrome = (tree.find(".//nav") is not None or tree.find(".//header") is not None
                  or any(_role(el) in ("navigation", "banner") for el in body.iter()))
    if not has_chrome:
        return []
    ids = {el.get("id") for el in tree.iter() if hasattr(el, "get") and el.get("id")}
    has_main = tree.find(".//main") is not None or any(_role(el) == "main" for el in body.iter())
    has_skip = any((a.get("href") or "").startswith("#") and (a.get("href") or "")[1:] in ids
                   for a in tree.iter("a"))
    if has_main or has_skip:
        return []
    children = list(body)
    chrome = [el for el in children
              if (isinstance(el.tag, str) and el.tag in ("nav", "header"))
              or _role(el) in ("navigation", "banner")]
    last = chrome[-1] if chrome else None
    to_wrap, after = [], last is None
    for el in children:
        if el is last:
            after = True
            continue
        if after and isinstance(el.tag, str) and el.tag not in ("script", "style"):
            to_wrap.append(el)
    if not to_wrap:
        return []
    main = body.makeelement("main", {"id": "main-content"})
    body.insert(list(body).index(to_wrap[0]), main)
    for el in to_wrap:
        main.append(el)   # lxml move — carries the element and its tail
    skip = body.makeelement("a", {"href": "#main-content", "class": "skip-link"})
    skip.text = "Skip to main content"
    body.insert(0, skip)
    return ["Added a skip link and main landmark to bypass repeated chrome · 2.4.1"]


# ── 2.4.3 Focus Order — reset positive tabindex to 0 (auto) ──
# Mirrors frontend/src/rules/wcag-2-4-3.js and scanner.py's HTML_POSITIVE_TABINDEX.
@_register("2.4.3", "auto")
def _fix_focus_order(tree, diffs=None) -> list:
    n = 0
    for el in tree.iter():
        ti = el.get("tabindex") if hasattr(el, "get") else None
        if ti is None:
            continue
        try:
            positive = int(ti) > 0
        except (ValueError, TypeError):
            continue
        if positive:
            el.set("tabindex", "0")
            n += 1
    return [f"Reset {n} positive tabindex value(s) so focus follows reading order · 2.4.3"] if n else []


# ── 2.4.6 Headings and Labels — close skipped heading levels (auto) ──
# The BACKEND heuristic (scanner.py HTML_HEADING_SKIP) is a *skipped heading level*
# (e.g. h1 → h3), which differs from the frontend wcag-2-4-6.js module (that one
# promotes visually-styled pseudo-headings). This fixer targets the scanner's
# heuristic: walk headings in document order and clamp any level that jumps by more
# than one down to prev+1, so the outline has no gaps and re-scans clean.
@_register("2.4.6", "auto")
def _fix_heading_skip(tree, diffs=None) -> list:
    heads = {"h1", "h2", "h3", "h4", "h5", "h6"}
    prev, changed = 0, 0
    for el in tree.iter():
        if not isinstance(el.tag, str) or el.tag not in heads:
            continue
        level = int(el.tag[1])
        if prev > 0 and level > prev + 1:
            level = prev + 1
            el.tag = f"h{level}"
            changed += 1
        prev = level
    return [f"Renumbered {changed} skipped heading level(s) so the outline has no gaps · 2.4.6"] if changed else []


# ── 2.4.7 Focus Visible — un-suppress focus outlines (auto) ──
# scanner.py's HTML_FOCUS_OUTLINE_SUPPRESSED fires on a static `outline:none|0`
# anywhere (a <style> block or an inline style) when interactive content exists.
# Adding a :focus-visible rule (as the frontend module does) does NOT clear that
# static regex, so this instead NEUTRALISES the suppression in place — `outline:
# revert` restores the UA default focus ring, which is exactly 2.4.7's intent and
# no longer matches the (none|0) predicate. Editing existing nodes only (no new
# <style>) avoids side-effecting the 1.4.10 reflow check.
_OUTLINE_SUPPRESS = re.compile(r"outline:\s*(none|0)\b", re.I)


@_register("2.4.7", "auto")
def _fix_focus_visible(tree, diffs=None) -> list:
    if next(tree.iter("a", "button", "input", "select", "textarea"), None) is None:
        return []
    n = 0
    for st in tree.iter("style"):
        txt = st.text or ""
        if txt and _OUTLINE_SUPPRESS.search(txt):
            st.text = _OUTLINE_SUPPRESS.sub("outline:revert", txt)
            n += 1
    for el in tree.iter():
        s = el.get("style") if hasattr(el, "get") else None
        if s and _OUTLINE_SUPPRESS.search(s):
            el.set("style", _OUTLINE_SUPPRESS.sub("outline:revert", s))
            n += 1
    return [f"Restored a visible keyboard focus indicator in {n} place(s) · 2.4.7"] if n else []


# ── 2.5.3 Label in Name — make the accessible name contain the visible text (auto) ──
# Mirrors frontend/src/rules/wcag-2-5-3.js and scanner.py's HTML_LABEL_NOT_IN_NAME.
@_register("2.5.3", "auto")
def _fix_label_in_name(tree, diffs=None) -> list:
    n = 0
    for el in list(tree.iter("a")) + list(tree.iter("button")):
        aria_raw = el.get("aria-label")
        if not aria_raw:
            continue
        aria = re.sub(r"\s+", " ", aria_raw).strip().lower()
        visible = re.sub(r"\s+", " ", el.text_content() or "").strip()[:80]
        if not visible or visible.lower() in aria:
            continue
        old = aria_raw.strip()
        el.set("aria-label", f"{visible} — {old}" if old else visible)
        n += 1
    return [f"Aligned {n} accessible name(s) with the visible label · 2.5.3"] if n else []


# ── 3.1.4 Abbreviations — wrap known abbreviations in <abbr title> (auto) ──
# Mirrors scanner.py's HTML_UNEXPANDED_ABBR. ABBR is duplicated from scanner.py by
# hand (same posture as scanner.py mirrors frontend utils.js) so the wrap clears the
# exact same detector. Handles lxml's text/tail model: an abbreviation in an
# element's .text becomes leading child <abbr>s; one in a child's .tail is inserted
# after that child. Wrapped text sits inside <abbr>, which the scanner skips, so a
# re-scan is clean and a re-run is idempotent.
ABBR = {
    "WCAG": "Web Content Accessibility Guidelines", "ADA": "Americans with Disabilities Act",
    "PDF": "Portable Document Format", "PPO": "Preferred Provider Organization",
    "HDHP": "High-Deductible Health Plan", "FSA": "Flexible Spending Account",
    "HSA": "Health Savings Account", "FAQ": "Frequently Asked Questions",
    "PII": "Personally Identifiable Information", "UTSW": "UT Southwestern", "HR": "Human Resources",
}
_ABBR_RE = re.compile(r"\b(" + "|".join(ABBR) + r")\b")
_ABBR_SKIP = {"abbr", "script", "style", "title"}


def _abbr_split(text: str):
    matches = list(_ABBR_RE.finditer(text))
    if not matches:
        return None
    leading = text[:matches[0].start()]
    pairs = []
    for i, m in enumerate(matches):
        nxt = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        pairs.append((m.group(1), text[m.end():nxt]))
    return leading, pairs


def _abbr_wrap(parent, anchor, text) -> int:
    """Wrap abbreviations found in `text`. anchor=None → the text is parent.text and
    new <abbr>s become parent's leading children; otherwise the text is anchor.tail
    and the <abbr>s are inserted right after anchor. Returns the number wrapped."""
    split = _abbr_split(text)
    if split is None:
        return 0
    leading, pairs = split
    base = 0 if anchor is None else list(parent).index(anchor) + 1
    if anchor is None:
        parent.text = leading
    else:
        anchor.tail = leading
    for i, (word, tail) in enumerate(pairs):
        ab = parent.makeelement("abbr", {"title": ABBR[word]})
        ab.text = word
        ab.tail = tail
        parent.insert(base + i, ab)
    return len(pairs)


@_register("3.1.4", "auto")
def _fix_abbr(tree, diffs=None) -> list:
    changed = 0
    for el in [e for e in tree.iter() if isinstance(e.tag, str)]:
        if el.tag in _ABBR_SKIP:
            continue
        if any(isinstance(a.tag, str) and a.tag in _ABBR_SKIP for a in el.iterancestors()):
            continue
        if el.text:
            changed += _abbr_wrap(el, None, el.text)
        parent = el.getparent()
        if el.tail and parent is not None:
            changed += _abbr_wrap(parent, el, el.tail)
    return [f"Expanded {changed} abbreviation(s) with <abbr> · 3.1.4"] if changed else []


# ── 2.4.4 Link Purpose — expand vague link text (proposer, not a FIXER) ──
# Runs OUTSIDE the FIXERS registry so 2.4.4 keeps its catalog fix_mode 'ai-assisted' (it
# still routes to HITL). A DETERMINISTIC derivation from the link target ("Annual-Report.pdf"
# → "Download Annual Report (PDF)") is applied inline — a real fix that clears the re-scan —
# and also surfaced as a High, one-click confirm; an opaque target with AI on gets a local
# text-model DRAFT surfaced as a Medium proposal (never applied). `proposals` collects
# {**proposal, "sc": "2.4.4", "applied": bool} for the worker to enqueue with a validated
# flag once the residual re-scan confirms the applied ones cleared.
def _propose_links(tree, proposals, *, ai_enabled: bool, diffs=None) -> None:
    if proposals is None:
        return
    import proposals as _prop
    drafted = 0
    for el in tree.iter("a"):
        if list(el):
            continue  # links wrapping elements (e.g. an <img>) aren't a plain-text case
        text = (el.text or "").strip()
        if not _prop.is_vague_link_text(text):
            continue
        href = el.get("href") or ""
        der = _prop.derive_link_text(href, "")
        if der and der.get("deterministic"):
            el.text = der["text"]
            _rec(diffs, "2.4.4", f'link text "{text or "(empty)"}"', der["text"], der["rationale"])
            proposals.append({**_prop.proposal(
                locator=href or der["text"], before=text or "(empty link text)",
                proposed_value=der["text"], rationale=der["rationale"],
                source="derived from the link target"), "sc": "2.4.4", "applied": True})
        elif ai_enabled and drafted < 20:
            try:
                import ai as _ai
                res = _ai.suggest_fix("2.4.4", "Link Purpose (In Context)", "A", "",
                                      detail=f'link text "{text}" → {href}') if _ai.is_available() else None
            except Exception:
                res = None
            if res and res.get("suggestion"):
                drafted += 1
                proposals.append({**_prop.proposal(
                    locator=href or text, before=text or "(empty link text)",
                    proposed_value=res["suggestion"],
                    rationale="link target is opaque; AI drafted descriptive text — confirm it names the destination",
                    source=f"AI text model ({res.get('model', 'llama')})"), "sc": "2.4.4", "applied": False})


def remediate_html(html_text: str, *, ai_enabled: bool = True, diffs=None,
                   proposals=None) -> tuple[str, list, list]:
    """Apply server-side HTML remediation.

    Returns (fixed_html, applied_changes, deferred_rule_ids):
      - applied_changes: human-readable descriptions of every fix applied.
      - deferred_rule_ids: WCAG SCs that have a finding but are 'ai-assisted' /
        'human-only' (not auto-fixed) — route these to HITL.
    `proposals` (optional out-list) collects AI-proposed one-click values (e.g. 2.4.4 link
    text) for the worker to enqueue onto the HITL queue.
    """
    tree = _lh.fromstring(html_text)
    applied: list[str] = []
    deferred: list[str] = []
    for sc, (mode, fn) in FIXERS.items():
        if mode == "auto":
            try:
                applied.extend(fn(tree, diffs))
            except Exception:
                # one fixer failing must never abort the whole remediation
                pass
        else:
            # ai-assisted / human-only → defer (HITL). When AI is off this is the
            # only path; when AI is on a later step may draft a fix for approval.
            deferred.append(sc)
    # 2.4.4 link-text expansion — deterministic fixes applied inline, drafts collected.
    try:
        _propose_links(tree, proposals, ai_enabled=ai_enabled, diffs=diffs)
        if proposals and any(p.get("applied") for p in proposals):
            applied.append("Expanded vague link text to describe its destination · 2.4.4")
    except Exception:
        pass
    # Provenance: self-identify the remediated HTML (generator meta + leading comment).
    if applied:
        from datetime import datetime, timezone
        from remediate_office import TOOL, VERSION
        _prov = f"{TOOL} {VERSION} — remediated {datetime.now(timezone.utc).strftime('%Y-%m-%d')}, WCAG 2.1 AA"
        head = tree.find('.//head')
        if head is not None:
            head.insert(0, head.makeelement('meta', {'name': 'generator', 'content': _prov}))
    fixed = _lh.tostring(tree, encoding="unicode")
    if applied:
        fixed = f"<!-- Remediated by {_prov} -->\n" + fixed
    return fixed, applied, deferred
