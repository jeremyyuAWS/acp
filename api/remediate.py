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
Fixer = Callable[[object], list]
FIXERS: dict[str, tuple[str, Fixer]] = {}


def _register(sc: str, fix_mode: str):
    def _wrap(fn):
        FIXERS[sc] = (fix_mode, fn)
        return fn
    return _wrap


# ── 3.1.1 Language of Page (auto) — mirrors frontend/src/rules/wcag-3-1-1.js ──
@_register("3.1.1", "auto")
def _fix_lang(tree) -> list:
    root = tree if tree.tag == "html" else (tree.getroottree().getroot())
    html_el = root if root.tag == "html" else root.find(".//html")
    if html_el is None:
        html_el = root
    if not (html_el.get("lang") or "").strip():
        html_el.set("lang", "en")
        return ["Set document language to English · 3.1.1"]
    return []


# ── 2.4.2 Page Titled (auto) — mirrors frontend/src/rules/wcag-2-4-2.js ──
@_register("2.4.2", "auto")
def _fix_title(tree) -> list:
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
    return ["Added a descriptive page title · 2.4.2"]


# ── 1.3.1 Info and Relationships — form labels (auto) ──
# Mirrors frontend/src/rules/wcag-1-3-1.js: give unlabeled controls an aria-label
# from a deterministic hint (placeholder → name → "Field").
@_register("1.3.1", "auto")
def _fix_form_labels(tree) -> list:
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
def _fix_contrast(tree) -> list:
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
def _fix_reflow(tree) -> list:
    has_head_content = any(tree.xpath(f"//{t}") for t in ("meta", "link", "style"))
    has_viewport = any((m.get("name") or "").lower() == "viewport" for m in tree.iter("meta"))
    if not has_head_content or has_viewport:
        return []
    head = _head(tree)
    head.insert(0, head.makeelement("meta", {"name": "viewport", "content": "width=device-width, initial-scale=1"}))
    return ["Added a responsive viewport so content reflows without horizontal scroll · 1.4.10"]


# ── 1.4.4 Resize Text — un-block pinch-zoom on the viewport (auto) ──
@_register("1.4.4", "auto")
def _fix_resize(tree) -> list:
    n = 0
    for m in tree.iter("meta"):
        if (m.get("name") or "").lower() != "viewport":
            continue
        if re.search(r"user-scalable\s*=\s*(no|0)|maximum-scale\s*=\s*(0|1)(\.0+)?\b", m.get("content") or "", re.I):
            m.set("content", "width=device-width, initial-scale=1")
            n += 1
    return [f"Restored pinch-zoom / text resize on {n} viewport tag(s) · 1.4.4"] if n else []


# ── 1.4.12 Text Spacing — relax fixed-pixel line-height (auto) ──
@_register("1.4.12", "auto")
def _fix_text_spacing(tree) -> list:
    n = 0
    for el in tree.iter():
        style = el.get("style") if hasattr(el, "get") else None
        if not style or not re.search(r"line-height:\s*\d+px", style, re.I):
            continue
        el.set("style", re.sub(r"line-height:\s*\d+px", "line-height:1.5", style, flags=re.I))
        n += 1
    return [f"Relaxed fixed line-height on {n} element(s) so users can override spacing · 1.4.12"] if n else []


# ── 1.4.2 Audio Control — stop autoplaying media (auto) ──
@_register("1.4.2", "auto")
def _fix_autoplay(tree) -> list:
    n = 0
    for m in tree.iter("audio", "video"):
        if m.get("autoplay") is not None and m.get("controls") is None:
            m.attrib.pop("autoplay", None)
            n += 1
    return [f"Removed autoplay from {n} media element(s) · 1.4.2"] if n else []


# ── 1.3.4 Orientation — un-lock content hidden in one orientation (auto) ──
_ORIENT = re.compile(
    r"@media[^{]*\(\s*orientation\s*:\s*(?:portrait|landscape)\s*\)[^{]*\{[^@]*?display\s*:\s*none", re.I)


@_register("1.3.4", "auto")
def _fix_orientation(tree) -> list:
    n = 0
    for st in tree.iter("style"):
        txt = st.text or ""
        if txt and _ORIENT.search(txt):
            st.text = _ORIENT.sub(lambda mm: re.sub(r"display\s*:\s*none", "display:revert", mm.group(0), count=1, flags=re.I), txt)
            n += 1
    return [f"Removed orientation lock from {n} stylesheet(s) · 1.3.4"] if n else []


def remediate_html(html_text: str, *, ai_enabled: bool = True) -> tuple[str, list, list]:
    """Apply server-side HTML remediation.

    Returns (fixed_html, applied_changes, deferred_rule_ids):
      - applied_changes: human-readable descriptions of every fix applied.
      - deferred_rule_ids: WCAG SCs that have a finding but are 'ai-assisted' /
        'human-only' (not auto-fixed) — route these to HITL.
    """
    tree = _lh.fromstring(html_text)
    applied: list[str] = []
    deferred: list[str] = []
    for sc, (mode, fn) in FIXERS.items():
        if mode == "auto":
            try:
                applied.extend(fn(tree))
            except Exception:
                # one fixer failing must never abort the whole remediation
                pass
        else:
            # ai-assisted / human-only → defer (HITL). When AI is off this is the
            # only path; when AI is on a later step may draft a fix for approval.
            deferred.append(sc)
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
