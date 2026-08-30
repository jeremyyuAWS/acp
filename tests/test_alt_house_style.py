"""House style reaches 1.1.1 alt drafts — and stops before the one place it must not.

WHY THIS EXISTS. ADR 0021 shapes AI drafts with an org's house style by injecting a guidance
block into the PROMPT (never the weights, never the applied value). `handlers._scan_file` passes
`guidance=_g(<sc>)` to every scan-time proposer that takes one — 1.3.3, 2.4.4/2.4.9, 2.4.6,
2.4.10 — and `alt_proposals_for_office` had no such parameter. So 1.1.1, the criterion that
produces MORE drafts than all the others put together (one per unlabelled image), was the single
one an org's house style could never reach. Not by a decision anyone made: by a missing argument.

THE SEPARATION THAT MATTERS. `describe_image_structured` has three outcomes and only two of them
are prose a house style may shape:

  * an IMAGE OF TEXT is transcribed verbatim and no model runs (WCAG 1.1.1 / F30 — the alt for
    an image of text IS that text). Guidance must not reach it: an org preference for, say,
    "start with the document's subject" would rewrite a verbatim quotation into a paraphrase,
    which is precisely the corruption that path exists to prevent.
  * a GROUNDED description is model-written, anchored in OCR text.
  * an UNGROUNDED description is model-written from pixels alone, and becomes a review proposal.

The last two take the guidance; the first returns before a prompt is ever built. That is easy to
read as an oversight, so it is asserted here rather than left to a comment.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))

import ai  # noqa: E402

HOUSE = "House style: name the business unit before the metric. Prefer 'colleague' to 'employee'."


# ── the guidance reaches both prompt builders ────────────────────────────────────

def test_the_grounded_prompt_carries_the_house_style():
    """The chart/diagram path. Anchored in OCR text, so the guidance is appended AFTER that
    anchor — a house style qualifies how the sentence reads, it does not replace what the
    image says."""
    prompt = ai._structured_vision_prompt("q3.docx", "Revenue by region North South", "", HOUSE)
    assert HOUSE in prompt
    assert "Text read from the image (OCR)" in prompt
    assert prompt.index("Text read from the image (OCR)") < prompt.index(HOUSE), (
        "the house style precedes the OCR anchor — guidance must qualify the instruction, not "
        "push the image's own text out of the model's attention")
    assert prompt.rstrip().endswith("Alt text:"), "the prompt no longer ends with its answer cue"


def test_the_ungrounded_prompt_carries_the_house_style():
    """The textless-photo path — the one that becomes a review proposal, and so the one a
    reviewer sees the house style in."""
    prompt = ai._vision_prompt("q3.docx", "", "", HOUSE)
    assert HOUSE in prompt


def test_both_prompts_are_unchanged_when_no_house_style_is_configured():
    """ACP_REVIEW_MEMORY is OFF by default and `_g` returns "" when it is. The default install
    must produce byte-identical prompts to before this change, or every existing alt draft
    shifts for orgs that never opted in."""
    assert ai._structured_vision_prompt("q3.docx", "Revenue", "ctx", "") == \
        ai._structured_vision_prompt("q3.docx", "Revenue", "ctx")
    assert ai._vision_prompt("q3.docx", "ctx", "", "") == ai._vision_prompt("q3.docx", "ctx")


# ── and stops at the transcription path ──────────────────────────────────────────

def test_an_image_of_text_is_transcribed_verbatim_and_never_sees_the_house_style(monkeypatch):
    """The honesty property. An image whose OCR reads as prose returns that prose as the alt,
    with no model call at all — so a house style cannot restyle a quotation of what the image
    literally says.

    Asserted by making any prompt build or model call a hard failure: if the transcription path
    ever starts routing through a prompt, this test says so rather than the change landing
    silently and an org's phrasing preference quietly editing transcribed text."""
    quote = ("Quarterly compliance summary. All regional teams completed the accessibility "
             "review ahead of the September deadline.")
    monkeypatch.setattr(ai, "_ocr_text_for_test", None, raising=False)

    class _FakeOcr:
        @staticmethod
        def ocr_text(_b):
            return quote

    monkeypatch.setitem(sys.modules, "ocr", _FakeOcr)

    def _boom(*a, **k):
        raise AssertionError("a model ran on the image-of-text path — the alt for an image of "
                             "text is that text, and no prompt should have been built")

    monkeypatch.setattr(ai, "_vision_generate", _boom)
    monkeypatch.setattr(ai, "_structured_vision_prompt", _boom)
    monkeypatch.setattr(ai, "_vision_prompt", _boom)

    out = ai.describe_image_structured(b"\x89PNG-not-really", allow_transcription=True,
                                       guidance=HOUSE)
    assert out is not None, "the transcription path stopped returning an alt"
    assert out["source"] == "ocr" and out["model"] is None
    assert HOUSE not in out["alt"], "the house style leaked into a verbatim transcription"
    assert "compliance summary" in out["alt"].lower()


# ── the wiring the criterion was missing ─────────────────────────────────────────

def test_alt_proposals_for_office_accepts_guidance():
    """The missing argument itself. Asserted on the signature because that absence — not any
    logic — is what kept 1.1.1 out of ADR 0021 for every other criterion's benefit."""
    import inspect

    import remediate_office
    sig = inspect.signature(remediate_office.alt_proposals_for_office)
    assert "guidance" in sig.parameters, (
        "alt_proposals_for_office has no guidance parameter — 1.1.1 is back to being the one "
        "scan-time proposer an org's house style cannot reach")
    assert sig.parameters["guidance"].default == "", (
        "guidance must default to empty so the keyless/memory-off install is unchanged")


def test_the_scan_path_passes_guidance_and_stamps_only_the_drafted_half():
    """1.1.1's batch is MIXED — deterministic chart datasheets plus model-written image drafts —
    so the house-style chip is stamped on the image drafts alone, before the enqueue, rather
    than passed to `_enqueue_proposals` (which stamps everything it is handed).

    Read off the source because the alternative is standing up a whole scan; the property being
    protected is a one-line call-site decision, and a reader changing it needs to be told why."""
    src = (ROOT / "api" / "handlers.py").read_text()
    assert 'guidance=_g("1.1.1")' in src, (
        "the scan-time alt proposer no longer receives house-style guidance")
    assert '_hs_alt = _hs("1.1.1")' in src and '"house_style": _hs_alt' in src, (
        "the image drafts are no longer stamped with the house style that shaped them")
    enqueue_111 = src[src.index('_enqueue_proposals(scan_id, filename, "1.1.1"'):][:220]
    assert "house_style" not in enqueue_111, (
        "1.1.1 now passes house_style to _enqueue_proposals, which stamps EVERY proposal in the "
        "batch — the deterministic chart datasheets would acquire a chip claiming an influence "
        "they never had")
