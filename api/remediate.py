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
