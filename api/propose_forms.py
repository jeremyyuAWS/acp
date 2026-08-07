"""AI-assisted LABEL proposals for unlabeled docx form fields (WCAG 3.3.2 Labels or
Instructions / 4.1.2 Name, Role, Value).

The scanner already DETECTS the gap — api/office_structure.py flags every interactive
content control (checkbox, date picker, dropdown, combo box, picture) whose <w:sdtPr> carries
no non-empty <w:alias> title (DOCX_FORM_FIELD_NO_LABEL, 3.3.2). Detection leaves the reviewer
a blank to fill. This module adds the PROPOSAL layer the alt-text lane already has: for each
unlabeled field it proposes a concrete label a human approves in one click.

Two honesty tiers, mirroring api/proposals.py:
  * DETERMINISTIC — a Word form's visible prompt text sits right beside the field
    ("Full name:  [   ]", or a label cell to the left of the input cell). That adjacent text
    IS the label; we derive it by reading the XML, no model. Surfaced as a Medium proposal
    (never auto-applied — a form label can't be validated by a re-scan, and even a correct
    derivation needs a human to confirm it matches intent).
  * LOCAL MODEL — a field with no adjacent prompt (mid-sentence, or a bare input) has no
    deterministic source; the local text model (api/ai.py → Ollama, no third-party AI) drafts
    a short label from the surrounding text. Always Low, always human-approved.

Lock-step with detection: the field predicates (_SDT / _SDT_PR / _SDT_INPUT_TYPE / _SDT_ALIAS)
are IMPORTED from api/office_structure.py rather than re-declared, so this proposes for exactly
the fields the scanner flags — never a field the detector would have passed, never missing one
it flags. The proposal dict shape (locator / before / proposed_value / rationale / source) and
the `proposal()` builder come from api/proposals.py, so these rows are indistinguishable from
every other proposal in the HITL queue.

Never raises — a parse/model failure yields no proposal and the finding falls back to plain
human review, exactly like the other proposers.
"""
from __future__ import annotations

import re
import zipfile

# Import the DETECTION primitives so proposal and detection stay in lock-step: we propose for
# precisely the content controls office_structure.docx_checks flags, no more, no less. These
# are private names by convention, but the coupling is deliberate — if they move, this import
# fails loudly rather than silently drifting out of sync with the detector.
from office_structure import _PARA, _SDT, _SDT_ALIAS, _SDT_INPUT_TYPE, _SDT_PR, _WT
from proposals import proposal

# ── Field type → the reader-facing noun used in the locator and rationale ──────
_FIELD_NOUN = {"checkbox": "checkbox", "date": "date picker",
               "dropDownList": "dropdown", "comboBox": "combo box",
               "picture": "picture field"}

_SDT_ID = re.compile(r'<w:id\s+w:val="([^"]*)"')
_HAS_LETTER = re.compile(r"[^\W\d_]", re.UNICODE)
# An enumerator / bullet that prefixes a prompt ("1. ", "• ") is not part of the label.
_ENUM_PREFIX = re.compile(r"^\s*(?:\d+[.)]|[•·▪◦\-–—*])\s+")
# A real form label is short; anything longer is body prose that happens to precede a field.
_LABEL_MAX_WORDS = 8
_LABEL_MAX_CHARS = 80


def _snip(text: str, n: int = 60) -> str:
    return re.sub(r"\s+", " ", text or "").strip()[:n]


def _clean_label(text: str) -> str:
    """Turn a chunk of adjacent text into a candidate label: collapse whitespace, keep only
    the trailing clause (the prompt immediately before the field, not an earlier sentence),
    drop a leading enumerator/bullet and a trailing colon or required-field asterisk."""
    t = re.sub(r"\s+", " ", text or "").strip()
    if not t:
        return ""
    t = re.split(r"(?<=[.!?])\s+", t)[-1].strip()   # last sentence/clause only
    t = _ENUM_PREFIX.sub("", t).strip()
    t = t.strip("*").strip()                          # drop required-field marker
    t = t.rstrip(":").strip()                         # drop the label/field separator colon
    return t


def _looks_like_label(t: str) -> bool:
    """A usable label has letters, is short (a prompt, not a paragraph), and isn't a
    placeholder glyph like '[ ]'."""
    if not t or not _HAS_LETTER.search(t):
        return False
    return 1 <= len(t.split()) <= _LABEL_MAX_WORDS and len(t) <= _LABEL_MAX_CHARS


def _current_para_text(before: str) -> str:
    """Visible text in the paragraph the field sits IN, before the field — the inline-label
    case ('Full name:  [field]'). Empty when the field opens its own paragraph (the label is
    stacked above it or in a table cell to the left), in which case the caller looks further
    back. `before` is document.xml sliced up to the field's start offset."""
    op = max(before.rfind("<w:p>"), before.rfind("<w:p "))
    if op == -1 or "</w:p>" in before[op:]:
        # No open paragraph, or the nearest one already closed before the field → not inline.
        return ""
    return "".join(_WT.findall(before[op:]))


def _prev_block_text(before: str) -> str:
    """Text of the last complete paragraph before the field — the stacked-label case, and the
    left-hand label cell of a two-cell table row (its paragraph is the last one before the
    field's own cell)."""
    for p in reversed(_PARA.findall(before)):
        t = "".join(_WT.findall(p)).strip()
        if t:
            return t
    return ""


def _following_text(doc: str, end: int) -> str:
    """First non-empty paragraph after the field — extra context for the model fallback when
    no prompt precedes the field."""
    for p in _PARA.findall(doc[end:]):
        t = "".join(_WT.findall(p)).strip()
        if t:
            return t
    return ""


def _content_text(inner: str) -> str:
    """The field's own placeholder/content text (e.g. 'Choose an item.', '[ ]'), shown as the
    proposal's `before` so the reviewer sees the thing being labelled. `inner` is the run of
    XML between <w:sdt> and </w:sdt>."""
    idx = inner.find("</w:sdtPr>")
    tail = inner[idx + len("</w:sdtPr>"):] if idx != -1 else inner
    return " ".join(_WT.findall(tail)).strip()


def _model_label(noun: str, context: str, filename: str) -> dict | None:
    """Draft a short label via the LOCAL text model (api/ai.py → Ollama). None when the model
    is unavailable or returns nothing label-shaped. No third-party AI — same privacy posture as
    every other proposer."""
    if not context:
        return None
    try:
        import ai as _ai
        if not _ai.is_available():
            return None
    except Exception:
        return None
    detail = (
        f'An unlabeled {noun} in a Word form has no title for assistive tech. Surrounding '
        f'document text: "{_snip(context, 200)}". Give a short label (2 to 4 words) naming '
        f'what the user enters or selects — just the label, no punctuation.')
    try:
        res = _ai.suggest_fix("3.3.2", "Labels or Instructions", "A", filename, detail=detail)
    except Exception:
        return None
    if not res or not res.get("suggestion"):
        return None
    label = _clean_label(res["suggestion"])
    if not _looks_like_label(label):
        return None
    return {"label": label, "model": res.get("model", "the local model")}


def proposals_from_document_xml(doc: str, *, filename: str = "",
                                ai_enabled: bool = True) -> list[dict]:
    """Pure generator: given a word/document.xml string, return one label proposal per
    unlabeled interactive content control. Deterministic where the field has an adjacent
    prompt; local-model-drafted (when ai_enabled and Ollama is up) where it does not; no
    proposal at all where neither yields a usable label (that field just stays a plain HITL
    deferral). Ordering follows document order."""
    out: list[dict] = []
    ordinal = 0
    for m in _SDT.finditer(doc):
        inner = m.group(1)
        pr = _SDT_PR.search(inner)
        if not pr:
            continue
        pr_xml = pr.group(1)
        tm = _SDT_INPUT_TYPE.search(pr_xml)
        if not tm:
            continue                       # not an interactive input gallery type — skip
        alias = _SDT_ALIAS.search(pr_xml)
        if alias and alias.group(1).strip():
            continue                       # already has a title/label — not a finding
        ordinal += 1
        noun = _FIELD_NOUN.get(tm.group(1), "form field")
        sid_m = _SDT_ID.search(pr_xml)
        sid = sid_m.group(1) if sid_m else ""

        before_xml = doc[:m.start()]
        adjacent = _current_para_text(before_xml) or _prev_block_text(before_xml)

        label = source = rationale = None
        candidate = _clean_label(adjacent)
        if _looks_like_label(candidate):
            label = candidate
            source = "derived from adjacent label text (deterministic)"
            rationale = (
                f'derived from the prompt text beside the {noun} ("{_snip(adjacent)}") — set it '
                f"as the field's title so assistive tech announces the field")
        elif ai_enabled:
            ctx = f"{adjacent} {_following_text(doc, m.end())}".strip()
            ml = _model_label(noun, ctx, filename)
            if ml:
                label = ml["label"]
                source = f"AI text model ({ml['model']}) — human judgement required"
                rationale = (
                    f"the {noun} has no adjacent prompt text; label suggested from the "
                    f"surrounding text — confirm it names what the user enters")
        if not label:
            continue

        # A STRUCTURAL locator, not the prose one this proposer first shipped with
        # ("unlabeled date picker #2"). An applier has to resolve a locator back to the exact
        # field a human approved, and an ordinal silently addresses a DIFFERENT field once any
        # earlier control is added, removed or labelled between proposal and approval — the
        # precise "approved a value for content the document no longer has" case every other
        # applier refuses. w:id is Word's own per-control identifier and survives edits
        # elsewhere in the document, so it is preferred; the ordinal remains only as a
        # last-resort fallback for controls that carry no w:id, and apply_docx_field_name
        # reports it unresolved rather than guessing when it cannot match.
        # Shape mirrors remediate_pdf's `pdf:field:…`.
        locator = f"docx:sdt:{sid}" if sid else f"docx:sdt:#{ordinal}"
        out.append(proposal(
            locator=locator,
            before=_content_text(inner) or "(no accessible name)",
            proposed_value=label,
            rationale=rationale,
            source=source))
    return out


def form_field_proposals(source, *, filename: str = "",
                         ai_enabled: bool = True) -> list[dict]:
    """Entry point for the remediation wiring: read word/document.xml from a docx (a path or a
    file-like of the docx bytes) and return its form-field label proposals. Never raises — any
    read/parse error yields []."""
    try:
        with zipfile.ZipFile(source) as zf:
            doc = zf.read("word/document.xml").decode("utf-8", "replace")
    except Exception:
        return []
    try:
        return proposals_from_document_xml(doc, filename=filename, ai_enabled=ai_enabled)
    except Exception:
        return []
