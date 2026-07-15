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
