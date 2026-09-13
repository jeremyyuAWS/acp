"""Unmapped PDF figures leave manual context, never fabricated applied-fix evidence.

The old page-caption implementation is retained, but ordinary remediation cannot
credit a figure from unrelated page OCR. Existing handler persistence and receipt
contracts remain available for other genuine fixes.
"""
import io
import sys
from pathlib import Path

import pytest

API = Path(__file__).resolve().parents[1] / "api"
sys.path.insert(0, str(API))

import remediate_pdf  # noqa: E402


def _png(w=600, h=800):
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (240, 240, 240)).save(buf, format="PNG")
    return buf.getvalue()


class _Figure(dict):
    """A /Figure struct element with no /Alt, on page 1."""
    def __init__(self):
        super().__init__()
        self["/S"] = "/Figure"


def _patch(monkeypatch, *, alt="Bar chart: Q3 revenue by region", page=1, render=True):
    import ai
    monkeypatch.setattr(ai, "vision_is_available", lambda: True)
    calls = []
    def describe(b, **kwargs):
        calls.append(b)
        return {"alt": alt, "grounded": True, "model": "moondream"} if alt else None
    monkeypatch.setattr(ai, "describe_image_structured", describe)
    figure = _Figure()
    monkeypatch.setattr(remediate_pdf, "_collect_figures", lambda root: [figure])
    monkeypatch.setattr(remediate_pdf, "_fig_alt", lambda f: None)     # unlabelled
    monkeypatch.setattr(remediate_pdf, "_resolve_page_number", lambda f, p: page)
    monkeypatch.setattr(remediate_pdf, "_render_page_png",
                        lambda *a, **k: _png() if render else None)

    class _Pdf:
        Root = {"/StructTreeRoot": object()}     # tagged → the figure path runs
    pdf = _Pdf()
    pdf.figure, pdf.calls = figure, calls
    return pdf


def _run(monkeypatch, **kw):
    pdf = _patch(monkeypatch, **kw)
    fixes: list = []
    applied, deferred = remediate_pdf._fix_pdf_figure_alt(
        pdf, "policy.pdf", ai_enabled=True, scan_id="s1", file="policy.pdf",
        applied_fixes=fixes)
    return fixes, applied, deferred


@pytest.mark.parametrize("alt", ["Bar chart: Q3 revenue by region", None])
def test_unmapped_figure_has_no_written_alt_or_applied_receipt(monkeypatch, alt):
    pdf = _patch(monkeypatch, alt=alt)
    fixes, props = [], []
    applied, deferred = remediate_pdf._fix_pdf_figure_alt(
        pdf, "policy.pdf", ai_enabled=True, scan_id=None, file="policy.pdf",
        applied_fixes=fixes, proposals=props)
    assert fixes == [] and applied == [] and deferred == 1
    assert "/Alt" not in pdf.figure and pdf.calls == []
    assert len(props) == 1 and props[0]["proposed_value"] == ""
    assert props[0]["kind"] == "pdf-figure-alt"
    assert "manual description required" in props[0]["source"]


def test_manual_context_uses_exact_locator_and_honest_provenance(monkeypatch):
    pdf = _patch(monkeypatch, page=7)
    props = []
    remediate_pdf._fix_pdf_figure_alt(pdf, "policy.pdf", ai_enabled=True,
        scan_id=None, file="policy.pdf", proposals=props)
    assert props[0]["locator"] == "pdf:fig:7:0"
    assert "page thumbnail is context" in props[0]["rationale"]
    assert "moondream" not in props[0]["source"]
    assert props[0].get("model_call_id") is None


def test_manual_thumbnail_is_real_png_sized_for_review_not_fix_receipt(monkeypatch):
    import base64
    from PIL import Image
    pdf = _patch(monkeypatch)
    props = []
    remediate_pdf._fix_pdf_figure_alt(pdf, "policy.pdf", ai_enabled=True,
        scan_id=None, file="policy.pdf", proposals=props)
    thumb = props[0]["thumb"]
    assert thumb.startswith("data:image/png;base64,")
    im = Image.open(io.BytesIO(base64.b64decode(thumb.split(",", 1)[1])))
    assert max(im.size) == remediate_pdf._PAGE_THUMB_EDGE == 320


def test_no_render_still_emits_manual_item_without_thumbnail(monkeypatch):
    pdf = _patch(monkeypatch, render=False)
    fixes, props = [], []
    applied, deferred = remediate_pdf._fix_pdf_figure_alt(pdf, "policy.pdf",
        ai_enabled=True, scan_id=None, file="policy.pdf", applied_fixes=fixes, proposals=props)
    assert fixes == [] and applied == [] and deferred == 1
    assert props[0].get("thumb") is None and not props[0]["proposed_value"]
    assert pdf.calls == []


def test_manual_figure_preserves_prior_genuine_fix_receipts(monkeypatch):
    pdf = _patch(monkeypatch)
    prior = {"rule_id": "SC_3_1_1", "value": "en", "source": "author", "thumb": None}
    fixes = [prior.copy()]
    applied, deferred = remediate_pdf._fix_pdf_figure_alt(pdf, "policy.pdf",
        ai_enabled=True, scan_id=None, file="policy.pdf", applied_fixes=fixes)
    assert fixes == [prior] and applied == [] and deferred == 1


def test_applied_fixes_optional_omission_and_ai_off_remain_manual(monkeypatch):
    pdf = _patch(monkeypatch)
    applied, deferred = remediate_pdf._fix_pdf_figure_alt(pdf, "policy.pdf",
        ai_enabled=False, scan_id=None, file="policy.pdf")
    assert applied == [] and deferred == 1 and pdf.calls == []


# ── remediate_pdf threads the list through ──

def test_remediate_pdf_accepts_applied_fixes():
    import inspect
    assert "applied_fixes" in inspect.signature(remediate_pdf.remediate_pdf).parameters


def test_the_handler_persists_both_formats_through_one_helper():
    h = (API / "handlers.py").read_text()
    code = "\n".join(l for l in h.split("\n") if not l.strip().startswith("#"))
    assert "def _record_applied_fixes" in code
    assert code.count("_record_applied_fixes(scan_id, filename, _applied_fixes)") == 2, \
        "both the pdf and the office branch must persist their applied fixes"
    assert "applied_fixes=_applied_fixes" in code
    # And the pdf branch actually asks for them.
    pdf_branch = code[code.index('if ext == "pdf":'):code.index("else:  # docx")]
    assert "applied_fixes=_applied_fixes" in pdf_branch


def test_retained_page_caption_receipt_contract_is_explicitly_legacy(monkeypatch):
    """Preserve the retired implementation's receipt format without claiming it ships.

    The live path above dispatches zero calls and never reaches this branch.
    Restoring AI captions requires exact figure evidence, not this fixture's page.
    """
    import base64
    from PIL import Image
    pdf = _patch(monkeypatch, page=7)
    fixes = []
    applied, deferred = remediate_pdf._fix_pdf_figure_alt_from_page_legacy(
        pdf, "policy.pdf", ai_enabled=True, scan_id=None, file="policy.pdf", applied_fixes=fixes)
    assert deferred == 0 and len(applied) == 1 and len(pdf.calls) == 1
    assert len(fixes) == 1
    assert set(fixes[0]) == {"rule_id", "value", "source", "thumb"}
    assert fixes[0]["rule_id"] == "SC_1_1_1"
    assert fixes[0]["value"] == str(pdf.figure["/Alt"]) == "Bar chart: Q3 revenue by region"
    assert "moondream" in fixes[0]["source"] and "page 7" in fixes[0]["source"]
    thumb = fixes[0]["thumb"]
    assert thumb.startswith("data:image/png;base64,")
    im = Image.open(io.BytesIO(base64.b64decode(thumb.split(",", 1)[1])))
    assert max(im.size) == remediate_pdf._FIX_THUMB_EDGE == 96
