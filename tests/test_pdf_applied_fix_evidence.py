"""A PDF's AI-written alt text is evidence, and must be recorded like any other.

`applied_fixes` is the certification record — store.py calls it "the AI wrote + its image
thumbnail". Office remediation appends {rule_id, value, source, thumb} rows to a list the
handler persists. `remediate_pdf` did not accept that list at all: it returned prose for the
job log and nothing else, so a PDF figure that the vision model captioned left NO row. No
value, no provenance, no picture — the certification evidence showed the fix never happened.

Both remediators now emit the same row shape, and one helper persists it for both formats.
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
    monkeypatch.setattr(ai, "describe_image_structured",
                        lambda b, **k: {"alt": alt, "grounded": True, "model": "moondream"} if alt else None)
    monkeypatch.setattr(remediate_pdf, "_collect_figures", lambda root: [_Figure()])
    monkeypatch.setattr(remediate_pdf, "_fig_alt", lambda f: None)     # unlabelled
    monkeypatch.setattr(remediate_pdf, "_resolve_page_number", lambda f, p: page)
    monkeypatch.setattr(remediate_pdf, "_render_page_png",
                        lambda *a, **k: _png() if render else None)

    class _Pdf:
        Root = {"/StructTreeRoot": object()}     # tagged → the figure path runs
    return _Pdf()


def _run(monkeypatch, **kw):
    pdf = _patch(monkeypatch, **kw)
    fixes: list = []
    applied, deferred = remediate_pdf._fix_pdf_figure_alt(
        pdf, "policy.pdf", ai_enabled=True, scan_id="s1", file="policy.pdf",
        applied_fixes=fixes)
    return fixes, applied, deferred


# ── the row now exists, in the office shape ──

def test_a_captioned_pdf_figure_records_an_evidence_row(monkeypatch):
    fixes, applied, deferred = _run(monkeypatch)
    assert deferred == 0 and len(applied) == 1
    assert len(fixes) == 1, "a PDF figure the AI captioned must leave a row in applied_fixes"


def test_the_row_carries_exactly_the_keys_the_handler_persists(monkeypatch):
    fixes, _, _ = _run(monkeypatch)
    assert set(fixes[0]) == {"rule_id", "value", "source", "thumb"}


def test_the_row_shape_matches_the_office_remediator(monkeypatch):
    # One helper persists both; a divergence here silently drops a column for one format.
    import re
    office = (API / "remediate_office.py").read_text()
    office_keys = set(re.findall(r'"(rule_id|value|source|thumb)":', office))
    fixes, _, _ = _run(monkeypatch)
    assert set(fixes[0]) == office_keys


def test_the_value_is_the_alt_text_actually_written(monkeypatch):
    fixes, _, _ = _run(monkeypatch, alt="Bar chart: Q3 revenue by region")
    assert fixes[0]["value"] == "Bar chart: Q3 revenue by region"
    assert fixes[0]["rule_id"] == "SC_1_1_1"


def test_the_source_names_the_page_render_not_the_image(monkeypatch):
    # remediate_pdf captions from a render of the whole PAGE. Saying "the image" would
    # misdescribe both the input and the thumbnail below it.
    fixes, _, _ = _run(monkeypatch, page=7)
    src = fixes[0]["source"]
    assert "page 7" in src and "render" in src
    assert "moondream" in src   # provenance names the model that ran


def test_the_thumb_is_a_real_png_data_url_sized_for_a_receipt(monkeypatch):
    import base64
    from PIL import Image
    fixes, _, _ = _run(monkeypatch)
    t = fixes[0]["thumb"]
    assert t.startswith("data:image/png;base64,")
    raw = base64.b64decode(t.split(",", 1)[1])
    im = Image.open(io.BytesIO(raw))
    assert max(im.size) == remediate_pdf._FIX_THUMB_EDGE == 96


def test_a_receipt_thumb_is_far_smaller_than_a_review_thumb(monkeypatch):
    # 25 figures at the reading-order card's 320px would put ~1 MB of base64 in one document's
    # applied_fixes. The receipt renders at 36px; it does not need the review surface's pixels.
    assert remediate_pdf._FIX_THUMB_EDGE < remediate_pdf._PAGE_THUMB_EDGE


# ── failure modes leave no row, and never raise ──

def test_a_figure_the_model_declines_records_nothing(monkeypatch):
    fixes, applied, deferred = _run(monkeypatch, alt=None)
    assert fixes == [] and applied == [] and deferred == 1


def test_a_page_that_will_not_render_records_nothing(monkeypatch):
    fixes, applied, deferred = _run(monkeypatch, render=False)
    assert fixes == [] and applied == [] and deferred == 1


def test_applied_fixes_is_optional_and_omitting_it_still_works(monkeypatch):
    # The scan path and older callers pass no list; the remediation must not depend on it.
    pdf = _patch(monkeypatch)
    applied, deferred = remediate_pdf._fix_pdf_figure_alt(
        pdf, "policy.pdf", ai_enabled=True, scan_id=None, file="policy.pdf")
    assert len(applied) == 1 and deferred == 0


def test_no_row_when_ai_is_off(monkeypatch):
    pdf = _patch(monkeypatch)
    fixes: list = []
    applied, deferred = remediate_pdf._fix_pdf_figure_alt(
        pdf, "policy.pdf", ai_enabled=False, scan_id=None, file="policy.pdf",
        applied_fixes=fixes)
    assert fixes == [] and applied == [] and deferred == 1


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
