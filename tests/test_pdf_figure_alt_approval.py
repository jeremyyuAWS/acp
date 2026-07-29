"""PDF figure alt APPROVAL loop (WCAG 1.1.1) — the office-parity gap.

A tagged /Figure the vision model can't ground used to vanish into a "N figures need alt" tally.
Now it emits a per-figure review card (stable `pdf:fig:{page}:{seq}` locator + page-render thumb),
and the reviewer's approved text is written back into that exact figure's /Alt by
`apply_pdf_figure_alt` — the same (bytes, {locator:value}) → (fixed, applied, unresolved) contract
as the office `apply_alt_text`, so the apply job branches only on extension.

pikepdf-only: exercises the new code without the partner PDF engine (remediate_pdf's re-scan).
"""
from __future__ import annotations
import io
import sys
from pathlib import Path

import pytest

pikepdf = pytest.importorskip("pikepdf")
pytest.importorskip("reportlab")
from reportlab.pdfgen import canvas  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))
import ai  # noqa: E402
import remediate_pdf as RP  # noqa: E402


def _tagged_pdf(path: Path, n_figs: int = 1) -> None:
    raw = path.with_name("raw-" + path.name)
    c = canvas.Canvas(str(raw))
    for i in range(n_figs):
        c.rect(120, 480 - i * 40, 200, 30, fill=1)
    c.showPage(); c.save()
    pdf = pikepdf.open(str(raw))
    page = pdf.pages[0].obj
    figs = []
    for _ in range(n_figs):
        fig = pikepdf.Dictionary(Type=pikepdf.Name("/StructElem"), S=pikepdf.Name("/Figure"), Pg=page, K=0)
        figs.append(pdf.make_indirect(fig))
    doc = pikepdf.Dictionary(Type=pikepdf.Name("/StructElem"), S=pikepdf.Name("/Document"))
    doc_ref = pdf.make_indirect(doc)
    doc.K = pikepdf.Array(figs)
    for f in figs:
        f.P = doc_ref
    st = pikepdf.Dictionary(Type=pikepdf.Name("/StructTreeRoot"), K=pikepdf.Array([doc_ref]))
    st_ref = pdf.make_indirect(st)
    doc.P = st_ref
    pdf.Root.StructTreeRoot = st_ref
    pdf.Root.MarkInfo = pikepdf.Dictionary(Marked=True)
    pdf.save(str(path)); pdf.close()


def _alts(data: bytes) -> list[str]:
    pdf = pikepdf.open(io.BytesIO(data))
    out = []
    figs = RP._collect_figures(pdf.Root["/StructTreeRoot"]) if "/StructTreeRoot" in pdf.Root else []
    for f in figs:
        out.append(str(f.get("/Alt", "")))
    pdf.close()
    return out


# ── deferred figure → per-figure review card ────────────────────────────────
def test_deferred_figure_emits_a_proposal_with_locator(tmp_path, monkeypatch):
    monkeypatch.setattr(ai, "vision_is_available", lambda: False)   # AI off → defer
    src = tmp_path / "f.pdf"; _tagged_pdf(src)
    pdf = pikepdf.open(str(src))
    props = []
    applied, deferred = RP._fix_pdf_figure_alt(pdf, str(src), ai_enabled=False,
                                               scan_id=None, file="f.pdf", proposals=props)
    assert deferred == 1 and applied == []
    assert len(props) == 1
    p = props[0]
    assert p["locator"] == "pdf:fig:1:0"
    assert p["kind"] == "pdf-figure-alt"
    assert "1.1.1" in p["before"]


def test_each_figure_gets_its_own_stable_locator(tmp_path, monkeypatch):
    monkeypatch.setattr(ai, "vision_is_available", lambda: False)
    src = tmp_path / "f3.pdf"; _tagged_pdf(src, n_figs=3)
    pdf = pikepdf.open(str(src))
    props = []
    RP._fix_pdf_figure_alt(pdf, str(src), ai_enabled=False, scan_id=None, file="f3.pdf", proposals=props)
    assert [p["locator"] for p in props] == ["pdf:fig:1:0", "pdf:fig:1:1", "pdf:fig:1:2"]


# ── grounded → written, ungrounded → review card (never asserted unattended) ─
#
# The office remediator has always made this split; the PDF path wrote /Alt for BOTH, so a pure
# vision guess — exactly the case most likely to be wrong — became the sentence a screen-reader
# user hears, in a file that now looks remediated. These pin the split closed.

_GUESS = "A person standing near a building"


def _stub_vision(monkeypatch, *, grounded: bool, alt: str = _GUESS):
    """Vision reachable and returning a description; `grounded` drives the honesty split.
    The page render is stubbed too, so this needs no PDF rasteriser."""
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (600, 800), (240, 240, 240)).save(buf, format="PNG")
    calls = {"n": 0}

    def fake(image_bytes, **kw):
        calls["n"] += 1
        return {"alt": alt, "grounded": grounded, "evidence": "stub", "model": "moondream"}

    monkeypatch.setattr(ai, "vision_is_available", lambda: True)
    monkeypatch.setattr(ai, "describe_image_structured", fake)
    monkeypatch.setattr(RP, "_render_page_png", lambda *a, **k: buf.getvalue())
    return calls


def _caption(tmp_path, monkeypatch, name, *, grounded, n_figs=2):
    src = tmp_path / name
    _tagged_pdf(src, n_figs=n_figs)
    calls = _stub_vision(monkeypatch, grounded=grounded)
    pdf = pikepdf.open(str(src))
    props, fixes = [], []
    applied, deferred = RP._fix_pdf_figure_alt(
        pdf, str(src), ai_enabled=True, scan_id=None, file=name,
        proposals=props, applied_fixes=fixes)
    out = io.BytesIO()
    pdf.save(out)
    pdf.close()
    return {"alts": _alts(out.getvalue()), "applied": applied, "deferred": deferred,
            "props": props, "fixes": fixes, "calls": calls["n"]}


def test_an_ungrounded_description_never_reaches_alt(monkeypatch, tmp_path):
    """THE regression: an ungrounded vision guess must not be written into /Alt."""
    r = _caption(tmp_path, monkeypatch, "ungrounded.pdf", grounded=False)
    assert r["alts"] == ["", ""], "an ungrounded guess was written into the PDF as fact"
    assert r["applied"] == [] and r["fixes"] == []      # nothing claimed as an applied fix
    assert r["deferred"] == 2                            # the 1.1.1 finding stays open


def test_an_ungrounded_description_becomes_a_review_card_with_its_draft(monkeypatch, tmp_path):
    # Withheld, not discarded: the reviewer gets the draft and the page picture, one card
    # per figure, each with the locator apply_pdf_figure_alt writes back through.
    r = _caption(tmp_path, monkeypatch, "cards.pdf", grounded=False)
    assert [p["locator"] for p in r["props"]] == ["pdf:fig:1:0", "pdf:fig:1:1"]
    assert all(p["proposed_value"] == _GUESS for p in r["props"])
    assert all(p["thumb"] and p["thumb"].startswith("data:image/png;base64,") for p in r["props"])
    assert all("confirm it matches the figure" in p["source"] for p in r["props"])


def test_a_grounded_description_is_still_applied_inline(monkeypatch, tmp_path):
    # The other half of the split: grounded work must keep flowing, or the fix is just a stop.
    r = _caption(tmp_path, monkeypatch, "grounded.pdf", grounded=True)
    assert r["alts"] == [_GUESS, _GUESS]
    assert len(r["applied"]) == 2 and r["deferred"] == 0
    assert len(r["fixes"]) == 2 and r["fixes"][0]["value"] == _GUESS


def test_the_office_and_pdf_paths_make_the_same_call(monkeypatch, tmp_path):
    """Parity with remediate_office._vision_alt — the split lives in both remediators."""
    src = (Path(__file__).resolve().parents[1] / "api" / "remediate_office.py").read_text()
    assert 'if res.get("grounded"):' in src, "office reference behaviour moved — recheck the PDF copy"
    assert RP._alt_write_anchor({"grounded": True}, b"", scan_id=None, file="f.pdf")
    assert RP._alt_write_anchor({"grounded": False, "alt": "x"}, b"", scan_id=None, file="f.pdf") is None


def _policy(monkeypatch, *, on: bool, verdict: str = "consistent"):
    """The opt-in auto-apply-validated policy + its independent second reading, both stubbed.
    `core` is injected rather than imported so this runs without the app's DB/scheduler deps."""
    from types import SimpleNamespace
    monkeypatch.setitem(sys.modules, "core", SimpleNamespace(
        store=SimpleNamespace(get_auto_apply_validated=lambda: on)))
    monkeypatch.setattr(ai, "validate_alt_text",
                        lambda img, alt, **kw: {"verdict": verdict, "second_opinion": "a building",
                                                "validator_model": "qwen2.5vl:7b"},
                        raising=False)


def test_a_validated_ungrounded_draft_is_applied_when_the_policy_is_on(monkeypatch, tmp_path):
    # Office parity: an ungrounded draft an INDEPENDENT second reading calls consistent may be
    # written — a measurement, not the model grading itself (ADR 0016).
    _policy(monkeypatch, on=True, verdict="consistent")
    r = _caption(tmp_path, monkeypatch, "validated.pdf", grounded=False)
    assert r["alts"] == [_GUESS, _GUESS] and r["deferred"] == 0
    assert "second reading" in r["fixes"][0]["source"]      # provenance says WHY it was written


def test_a_divergent_second_reading_still_defers(monkeypatch, tmp_path):
    _policy(monkeypatch, on=True, verdict="divergent")
    r = _caption(tmp_path, monkeypatch, "divergent.pdf", grounded=False)
    assert r["alts"] == ["", ""] and r["deferred"] == 2


def test_the_policy_is_off_by_default_so_ungrounded_defers(monkeypatch, tmp_path):
    _policy(monkeypatch, on=False)
    r = _caption(tmp_path, monkeypatch, "policyoff.pdf", grounded=False)
    assert r["alts"] == ["", ""] and r["deferred"] == 2


def test_a_deferred_figure_does_not_burn_the_vision_budget_forever(monkeypatch, tmp_path):
    # Budget counts model CALLS, not writes. It used to decrement only on a successful write,
    # so a document of ungrounded figures would call the model once per figure unbounded.
    monkeypatch.setattr(RP, "_VISION_MAX_FIGURES", 2)
    r = _caption(tmp_path, monkeypatch, "budget.pdf", grounded=False, n_figs=5)
    assert r["calls"] == 2                     # budget spent → the rest defer without a call
    assert r["deferred"] == 5 and r["alts"] == ["", "", "", "", ""]


# ── apply-on-approval writes /Alt back by locator ───────────────────────────
def test_apply_writes_approved_alt_into_the_right_figure(tmp_path):
    src = tmp_path / "a.pdf"; _tagged_pdf(src, n_figs=3)
    data = src.read_bytes()
    fixed, applied, unresolved = RP.apply_pdf_figure_alt(
        data, {"pdf:fig:1:1": "A quarterly revenue bar chart"})
    assert unresolved == []
    assert len(applied) == 1 and applied[0]["locator"] == "pdf:fig:1:1"
    assert _alts(fixed) == ["", "A quarterly revenue bar chart", ""]   # only figure 1 written


def test_apply_round_trips_the_proposal_locator(tmp_path, monkeypatch):
    """The locator the proposal emits must resolve at apply time — the whole contract."""
    monkeypatch.setattr(ai, "vision_is_available", lambda: False)
    src = tmp_path / "rt.pdf"; _tagged_pdf(src)
    pdf = pikepdf.open(str(src)); props = []
    RP._fix_pdf_figure_alt(pdf, str(src), ai_enabled=False, scan_id=None, file="rt.pdf", proposals=props)
    locator = props[0]["locator"]
    fixed, applied, unresolved = RP.apply_pdf_figure_alt(src.read_bytes(), {locator: "Author confirmed alt"})
    assert not unresolved and _alts(fixed) == ["Author confirmed alt"]


def test_apply_unresolved_locator_is_reported_not_guessed(tmp_path):
    src = tmp_path / "u.pdf"; _tagged_pdf(src)
    fixed, applied, unresolved = RP.apply_pdf_figure_alt(src.read_bytes(), {"pdf:fig:9:9": "nope"})
    assert applied == [] and unresolved == ["pdf:fig:9:9"]
    assert _alts(fixed) == [""]                       # nothing written


def test_apply_ignores_non_pdf_locators(tmp_path):
    """Office locators (word/document.xml#rId2) are not this function's job — pass them through."""
    src = tmp_path / "mix.pdf"; _tagged_pdf(src)
    _fixed, applied, unresolved = RP.apply_pdf_figure_alt(
        src.read_bytes(), {"word/document.xml#rId2": "office value"})
    assert applied == [] and unresolved == ["word/document.xml#rId2"]


def test_apply_blank_value_writes_nothing(tmp_path):
    src = tmp_path / "b.pdf"; _tagged_pdf(src)
    fixed, applied, unresolved = RP.apply_pdf_figure_alt(src.read_bytes(), {"pdf:fig:1:0": "   "})
    assert applied == [] and _alts(fixed) == [""]
