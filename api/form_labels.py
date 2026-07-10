"""Deterministic labels for docx content-control form fields (WCAG 3.3.2).

A Word form field is a content control (``w:sdt``) of an interactive input
gallery type — checkbox, date picker, dropdown, combo box, picture. It fails
3.3.2 when it carries no title/alias a screen reader can announce. But most of
the time the label is sitting right next to it as ordinary VISIBLE text —
"Name:" in the run before it, or the left-hand cell of its table row. This
module reads that adjacent text so the remediator can WRITE it into the
control's ``<w:alias>`` deterministically: no model, no approval. Only a
genuinely BARE field — one with no adjacent text to borrow — is left for review
to label; a label is never invented deterministically for a bare field.

This module is pure detection/extraction — it never mutates the tree except via
the explicit :func:`set_alias` writer the remediator calls. It is kept in
lock-step with the ``DOCX_FORM_FIELD_NO_LABEL`` detector in ``office_structure``
(same input gallery types, same "missing/empty alias = unlabelled" gate) so a
fix produced here clears that finding on the residual re-scan.
"""
from __future__ import annotations

import re

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

# The interactive input gallery types that are unambiguously "a field a user
# fills in" — identical to office_structure._SDT_INPUT_TYPE. w:text/w:richText
# are deliberately excluded (Word also uses them for non-input placeholders).
_INPUT_TYPES = ("checkbox", "date", "dropDownList", "comboBox", "picture")

_HAS_LETTER = re.compile(r"[^\W\d_]", re.UNICODE)

# A field label is a short caption/instruction, not a paragraph of prose. This
# caps both what we ACCEPT as a label and how long a value we write.
_MAX_LABEL_WORDS = 8
_MAX_LABEL_CHARS = 80

# The immediately-preceding paragraph is the weakest signal (it could be an
# unrelated sentence), so it only counts as a label when it reads like one: a
# trailing separator (a colon) or a genuinely short caption.
_PREV_PARA_MAX_WORDS = 6
_LABEL_SEPARATORS = ":：*"


def _q(tag: str) -> str:
    return f"{{{W}}}{tag}"


def _text(el) -> str:
    return "".join(t.text or "" for t in el.iter(_q("t")))


def _clean(s: str) -> str:
    """Normalise a candidate: collapse whitespace, drop trailing label separators."""
    s = re.sub(r"\s+", " ", (s or "").replace("\xa0", " ")).strip()
    return s.rstrip(_LABEL_SEPARATORS + " ").strip()


def _ancestor(el, tag: str):
    p = el.getparent()
    q = _q(tag)
    while p is not None:
        if p.tag == q:
            return p
        p = p.getparent()
    return None


def _has_input_field(el) -> bool:
    return any(is_input_field(s) for s in el.iter(_q("sdt")))


def _is_label(s: str) -> bool:
    return bool(s) and bool(_HAS_LETTER.search(s)) and len(s.split()) <= _MAX_LABEL_WORDS


# --- content-control classification (mirrors the office_structure detector) ---

def is_input_field(sdt) -> bool:
    """True when this ``w:sdt`` is one of the interactive input gallery types."""
    pr = sdt.find(_q("sdtPr"))
    if pr is None:
        return False
    return any(pr.find(_q(t)) is not None for t in _INPUT_TYPES)


def current_alias(sdt) -> str | None:
    pr = sdt.find(_q("sdtPr"))
    if pr is None:
        return None
    alias = pr.find(_q("alias"))
    return None if alias is None else alias.get(_q("val"))


def is_unlabelled(sdt) -> bool:
    """An input field with no (or empty) alias — exactly what the detector flags."""
    return is_input_field(sdt) and not (current_alias(sdt) or "").strip()


# --- adjacent-label extraction (deterministic, conservative) ---

def _inline_label(sdt) -> str:
    """Visible text in the SAME paragraph, before this control ("Date of birth: [ ]").

    Only plain runs count: text inside a *prior* content control on the same line
    (two fields on one row) is reset out, so we borrow just the caption that
    immediately precedes this field.
    """
    p = _ancestor(sdt, "p")
    if p is None:
        return ""
    # the control may be nested (e.g. inside a hyperlink); find the p-level child
    # that contains it so we can walk that child's preceding siblings.
    node = sdt
    while node is not None and node.getparent() is not p:
        node = node.getparent()
    if node is None:
        return ""
    buf: list[str] = []
    for child in p:
        if child is node:
            break
        if child.tag == _q("sdt"):
            buf = []                       # a prior field resets the label buffer
        else:
            buf.append(_text(child))
    return _clean("".join(buf))


def _cell_label(sdt) -> str:
    """Text of the nearest non-empty preceding cell in the same table row
    (the classic two-column "| Full name | [field] |" form layout)."""
    tc = _ancestor(sdt, "tc")
    if tc is None:
        return ""
    tr = tc.getparent()
    if tr is None or tr.tag != _q("tr"):
        return ""
    cells = [c for c in tr if c.tag == _q("tc")]
    try:
        idx = cells.index(tc)
    except ValueError:
        return ""
    for c in reversed(cells[:idx]):
        if _has_input_field(c):
            continue                       # a neighbouring field is not a label
        lab = _clean(_text(c))
        if _is_label(lab):
            return lab
    return ""


def _prev_para_label(sdt) -> tuple[str, str]:
    """Text of the immediately-preceding sibling paragraph (a label on its own
    line, above the field). Returns (cleaned, raw) — the raw is used to check for
    a trailing colon, the strongest "this is a label" signal."""
    p = _ancestor(sdt, "p")
    if p is None:
        return "", ""
    prev = p.getprevious()
    while prev is not None and prev.tag != _q("p"):
        prev = prev.getprevious()
    if prev is None or _has_input_field(prev):
        return "", ""
    raw = _text(prev)
    return _clean(raw), raw


def adjacent_label(sdt) -> str:
    """The deterministic label for an unlabelled field, or "" if it is bare.

    Priority: inline caption in the same paragraph, then the preceding table
    cell, then the preceding paragraph (accepted only when it clearly reads as a
    label). Never invents text — an empty return means "route to review".
    """
    inline = _inline_label(sdt)
    if _is_label(inline):
        return inline[:_MAX_LABEL_CHARS].strip()
    cell = _cell_label(sdt)
    if _is_label(cell):
        return cell[:_MAX_LABEL_CHARS].strip()
    prev, prev_raw = _prev_para_label(sdt)
    if _is_label(prev) and (
        prev_raw.rstrip().endswith(tuple(_LABEL_SEPARATORS))
        or len(prev.split()) <= _PREV_PARA_MAX_WORDS
    ):
        return prev[:_MAX_LABEL_CHARS].strip()
    return ""


def plan_labels(root) -> tuple[list[tuple[object, str]], int]:
    """Walk the document; for every UNLABELLED input content control, decide a
    deterministic label from adjacent visible text.

    Returns ``(labelled, bare)``:

      * ``labelled`` — ``[(sdt_element, label_text)]`` to write into ``<w:alias>``
        (the deterministic auto-fix, no approval).
      * ``bare`` — count of unlabelled input controls with no adjacent text; these
        stay a finding and route to human/AI review (never labelled here).
    """
    labelled: list[tuple[object, str]] = []
    bare = 0
    for sdt in root.iter(_q("sdt")):
        if not is_unlabelled(sdt):
            continue
        label = adjacent_label(sdt)
        if label:
            labelled.append((sdt, label))
        else:
            bare += 1
    return labelled, bare


def set_alias(sdt, label: str) -> None:
    """Write ``label`` into this control's ``<w:alias w:val="…"/>`` (its Title),
    which is exactly what the analyser reads for 3.3.2. Creates the element in its
    schema position (after ``w:rPr``) when absent; every other byte is untouched."""
    pr = sdt.find(_q("sdtPr"))
    if pr is None:                          # an input field always has one, but be safe
        pr = sdt.makeelement(_q("sdtPr"), {})
        sdt.insert(0, pr)
    alias = pr.find(_q("alias"))
    if alias is None:
        alias = pr.makeelement(_q("alias"), {})
        rPr = pr.find(_q("rPr"))
        pr.insert(list(pr).index(rPr) + 1 if rPr is not None else 0, alias)
    alias.set(_q("val"), label)
