"""ADR 0024 Tier A — render-gated criteria structural proxies (no rendering): 1.4.10 Reflow,
1.4.12 Text Spacing, 1.4.4 Resize Text, and the 1.4.3 hybrid (text over a non-solid fill).

Each emits an advisory REVIEW finding (severity REVIEW) from a deterministic OOXML fact, and
nothing when the signal is absent — never a certified pass. Hand-built zip/XML fixtures.
"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

import office_structure as os_  # noqa: E402


def _zip(tmp: Path, name: str, parts: dict[str, str]) -> Path:
    p = tmp / name
    with zipfile.ZipFile(p, "w") as z:
        for n, data in parts.items():
            z.writestr(n, data)
    return p


def _docx(tmp, body: str) -> Path:
    return _zip(tmp, "d.docx", {"word/document.xml": f"<w:document><w:body>{body}</w:body></w:document>"})


def _pptx(tmp, *shapes: str) -> Path:
    tree = "".join(shapes)
    return _zip(tmp, "d.pptx", {"ppt/slides/slide1.xml": f"<p:sld><p:cSld><p:spTree>{tree}</p:spTree></p:cSld></p:sld>"})


def _wcags(f):
    return {x["wcag"] for x in f}


def _all_review(f):
    return all(x["severity"] == "REVIEW" and x.get("advisory") is True for x in f)


def _cols(n, tag="w"):
    return "".join(f"<{tag}:gridCol/>" for _ in range(n))


# ── 1.4.10 Reflow — wide table ────────────────────────────────────────────────
def test_docx_wide_table_flags_reflow(tmp_path):
    p = _docx(tmp_path, f"<w:tbl><w:tblGrid>{_cols(8)}</w:tblGrid></w:tbl>")
    f = os_.office_reflow_checks(p, ".docx")
    assert _wcags(f) == {"1.4.10 Reflow"} and _all_review(f)
    assert "8 columns" in f[0]["detail"]


def test_docx_narrow_table_not_flagged(tmp_path):
    p = _docx(tmp_path, f"<w:tbl><w:tblGrid>{_cols(7)}</w:tblGrid></w:tbl>")
    assert os_.office_reflow_checks(p, ".docx") == []


def _cols_w(widths, tag="w", wattr="w:w"):
    return "".join(f'<{tag}:gridCol {wattr}="{x}"/>' for x in widths)


def test_docx_reflow_reports_measured_narrowest_column(tmp_path):
    # 8 columns, one very tight (200 twips) among wide ones (3000 each) → narrowest ≈ 0.9% → ~3px.
    widths = [3000] * 7 + [200]
    p = _docx(tmp_path, f"<w:tbl><w:tblGrid>{_cols_w(widths)}</w:tblGrid></w:tbl>")
    f = os_.office_reflow_checks(p, ".docx")
    assert _wcags(f) == {"1.4.10 Reflow"} and _all_review(f)
    assert "8 columns" in f[0]["detail"]
    assert "narrowest column" in f[0]["detail"] and "px" in f[0]["detail"]


def test_narrowest_column_fraction_is_honest():
    assert os_._narrowest_column_fraction(4, [100, 100, 100, 100]) == 0.25
    assert abs(os_._narrowest_column_fraction(8, [3000] * 7 + [200]) - 200 / 21200) < 1e-9
    # Missing / incomplete widths → None, never a guessed fraction.
    assert os_._narrowest_column_fraction(8, []) is None
    assert os_._narrowest_column_fraction(8, [100, 100]) is None
    assert os_._narrowest_column_fraction(2, [0, 0]) is None


def test_pptx_wide_table_flags_reflow(tmp_path):
    p = _pptx(tmp_path, f"<a:tbl><a:tblGrid>{_cols(9, 'a')}</a:tblGrid></a:tbl>")
    assert any(x["wcag"].startswith("1.4.10") for x in os_.office_reflow_checks(p, ".pptx"))


# ── 1.4.12 Text Spacing — exact line spacing ──────────────────────────────────
def test_docx_exact_line_spacing_flags(tmp_path):
    para = '<w:p><w:pPr><w:spacing w:lineRule="exact" w:line="240"/></w:pPr></w:p>'
    p = _docx(tmp_path, para * 3)
    f = os_.office_text_spacing_checks(p, ".docx")
    assert _wcags(f) == {"1.4.12 Text Spacing"} and _all_review(f)


def test_docx_below_threshold_not_flagged(tmp_path):
    para = '<w:p><w:pPr><w:spacing w:lineRule="exact"/></w:pPr></w:p>'
    assert os_.office_text_spacing_checks(_docx(tmp_path, para * 2), ".docx") == []


def test_docx_auto_spacing_not_flagged(tmp_path):
    para = '<w:p><w:pPr><w:spacing w:lineRule="auto" w:line="360"/></w:pPr></w:p>'
    assert os_.office_text_spacing_checks(_docx(tmp_path, para * 5), ".docx") == []


def test_docx_exact_spacing_reports_measured_ratio(tmp_path):
    # 12pt fixed line box (w:line=240) on a 12pt font (w:sz=24) → ratio 1.0, below WCAG's 1.5×.
    para = ('<w:p><w:pPr><w:spacing w:lineRule="exact" w:line="240"/></w:pPr>'
            '<w:r><w:rPr><w:sz w:val="24"/></w:rPr><w:t>x</w:t></w:r></w:p>')
    f = os_.office_text_spacing_checks(_docx(tmp_path, para * 3), ".docx")
    assert _wcags(f) == {"1.4.12 Text Spacing"} and _all_review(f)
    assert "font size" in f[0]["detail"] and "1.0" in f[0]["detail"]


def test_docx_exact_spacing_below_font_reports_overlap(tmp_path):
    # 9pt line box (w:line=180) on a 12pt font → 0.75×: the box is shorter than the text.
    para = ('<w:p><w:pPr><w:spacing w:lineRule="exact" w:line="180"/></w:pPr>'
            '<w:r><w:rPr><w:sz w:val="24"/></w:rPr><w:t>x</w:t></w:r></w:p>')
    f = os_.office_text_spacing_checks(_docx(tmp_path, para * 3), ".docx")
    assert "0.75" in f[0]["detail"] and "overlap" in f[0]["detail"]


def test_pptx_exact_spacing_reports_measured_ratio(tmp_path):
    para = ('<a:p><a:pPr><a:lnSpc><a:spcPts val="1200"/></a:lnSpc></a:pPr>'
            '<a:r><a:rPr sz="1200"/><a:t>x</a:t></a:r></a:p>')
    p = _zip(tmp_path, "s.pptx", {"ppt/slides/slide1.xml": f"<p:sld>{para * 3}</p:sld>"})
    assert "font size" in os_.office_text_spacing_checks(p, ".pptx")[0]["detail"]


def test_min_exact_line_height_ratio_is_honest():
    docx = ('<w:p><w:pPr><w:spacing w:lineRule="exact" w:line="240"/></w:pPr>'
            '<w:r><w:rPr><w:sz w:val="24"/></w:rPr></w:r></w:p>')
    assert os_._min_exact_line_height_ratio(docx, ".docx") == 1.0
    # No font size to compare against → cannot measure → None (never guessed).
    assert os_._min_exact_line_height_ratio(
        '<w:p><w:pPr><w:spacing w:lineRule="exact" w:line="240"/></w:pPr></w:p>', ".docx") is None
    # Auto (non-exact) spacing isn't measured even with a font size.
    assert os_._min_exact_line_height_ratio(
        '<w:p><w:pPr><w:spacing w:lineRule="auto" w:line="360"/></w:pPr>'
        '<w:r><w:rPr><w:sz w:val="24"/></w:rPr></w:r></w:p>', ".docx") is None
    pptx = ('<a:p><a:pPr><a:lnSpc><a:spcPts val="900"/></a:lnSpc></a:pPr>'
            '<a:r><a:rPr sz="1200"/></a:r></a:p>')
    assert abs(os_._min_exact_line_height_ratio(pptx, ".pptx") - 0.75) < 1e-9


def test_pptx_exact_line_spacing_flags(tmp_path):
    para = '<a:p><a:pPr><a:lnSpc><a:spcPts val="1200"/></a:lnSpc></a:pPr></a:p>'
    p = _zip(tmp_path, "s.pptx", {"ppt/slides/slide1.xml": f"<p:sld>{para * 3}</p:sld>"})
    assert any(x["wcag"].startswith("1.4.12") for x in os_.office_text_spacing_checks(p, ".pptx"))


# ── 1.4.4 Resize Text — fixed-size (no-autofit) text box with lots of text ─────
def test_pptx_fixed_text_box_flags_resize(tmp_path):
    long_text = "word " * 80          # > 300 chars
    sp = f"<p:sp><p:txBody><a:bodyPr><a:noAutofit/></a:bodyPr><a:p><a:r><a:t>{long_text}</a:t></a:r></a:p></p:txBody></p:sp>"
    f = os_.pptx_resize_text_checks(_pptx(tmp_path, sp))
    assert _wcags(f) == {"1.4.4 Resize Text"} and _all_review(f)


def test_pptx_short_fixed_box_not_flagged(tmp_path):
    sp = "<p:sp><p:txBody><a:bodyPr><a:noAutofit/></a:bodyPr><a:p><a:r><a:t>Short label</a:t></a:r></a:p></p:txBody></p:sp>"
    assert os_.pptx_resize_text_checks(_pptx(tmp_path, sp)) == []


def test_resize_text_locators_from_path_and_bytes(tmp_path):
    # ADR 0024 Tier B.2 targets: no-autofit boxes >=300 chars, attributable by cNvPr, from Path OR bytes.
    long_text = "word " * 80
    sp = f'<p:sp><p:nvSpPr><p:cNvPr id="7" name="Body 1"/></p:nvSpPr><p:txBody><a:bodyPr><a:noAutofit/></a:bodyPr><a:p><a:r><a:t>{long_text}</a:t></a:r></a:p></p:txBody></p:sp>'
    p = _pptx(tmp_path, sp)
    assert os_.resize_text_locators(p) == os_.resize_text_locators(p.read_bytes())
    locs = os_.resize_text_locators(p)
    assert len(locs) == 1 and locs[0]["shape"] == "Body 1"
    # The Tier-A finding now carries the locator for Tier B (assert before _pptx reuses the path).
    assert os_.pptx_resize_text_checks(p)[0]["locators"][0]["shape"] == "Body 1"
    # An autofit box (or a short one) is not a target.
    autofit = f'<p:sp><p:nvSpPr><p:cNvPr id="8" name="Auto"/></p:nvSpPr><p:txBody><a:bodyPr><a:normAutofit/></a:bodyPr><a:p><a:r><a:t>{long_text}</a:t></a:r></a:p></p:txBody></p:sp>'
    assert os_.resize_text_locators(_pptx(tmp_path, autofit)) == []


def test_pptx_autofit_box_not_flagged(tmp_path):
    long_text = "word " * 80
    sp = f"<p:sp><p:txBody><a:bodyPr><a:normAutofit/></a:bodyPr><a:p><a:r><a:t>{long_text}</a:t></a:r></a:p></p:txBody></p:sp>"
    assert os_.pptx_resize_text_checks(_pptx(tmp_path, sp)) == []


# ── 1.4.3 hybrid — text over a picture / gradient fill ────────────────────────
def test_pptx_text_over_picture_flags_hybrid_contrast(tmp_path):
    sp = '<p:sp><p:nvSpPr><p:cNvPr id="5" name="Title 1"/></p:nvSpPr><p:spPr><a:blipFill><a:blip/></a:blipFill></p:spPr><p:txBody><a:p><a:r><a:t>Read me</a:t></a:r></a:p></p:txBody></p:sp>'
    f = os_.pptx_complex_bg_contrast_checks(_pptx(tmp_path, sp))
    assert _wcags(f) == {"1.4.3 Contrast (Minimum)"} and _all_review(f)
    assert "picture" in f[0]["detail"]
    # ADR 0024 Tier B: the finding carries a per-shape locator for the render-verify endpoint.
    locs = f[0].get("locators")
    assert locs and locs[0]["shape"] == "Title 1" and locs[0]["kind"] == "picture"
    assert locs[0]["part"].endswith("slide1.xml")


def test_hybrid_contrast_locators_from_path_and_bytes(tmp_path):
    # The endpoint re-derives locators from source BYTES; the detector from a PATH — same result.
    sp1 = '<p:sp><p:nvSpPr><p:cNvPr id="5" name="Title 1"/></p:nvSpPr><p:spPr><a:blipFill/></p:spPr><p:txBody><a:p><a:r><a:t>Over the photo</a:t></a:r></a:p></p:txBody></p:sp>'
    sp2 = '<p:sp><p:nvSpPr><p:cNvPr id="6" name="Body 2"/></p:nvSpPr><p:spPr><a:gradFill/></p:spPr><p:txBody><a:p><a:r><a:t>Over gradient</a:t></a:r></a:p></p:txBody></p:sp>'
    p = _pptx(tmp_path, sp1, sp2)
    from_path = os_.hybrid_contrast_locators(p)
    from_bytes = os_.hybrid_contrast_locators(p.read_bytes())
    assert from_path == from_bytes
    assert [(loc["shape"], loc["kind"]) for loc in from_path] == [("Title 1", "picture"), ("Body 2", "gradient")]
    # A deck with no text-over-complex-fill shape yields no targets.
    plain = '<p:sp><p:nvSpPr><p:cNvPr id="9" name="Plain"/></p:nvSpPr><p:spPr><a:solidFill/></p:spPr><p:txBody><a:p><a:r><a:t>hi</a:t></a:r></a:p></p:txBody></p:sp>'
    assert os_.hybrid_contrast_locators(_pptx(tmp_path, plain)) == []
    assert os_.hybrid_contrast_locators(b"not a zip") == []


def test_pptx_text_over_gradient_flags(tmp_path):
    sp = "<p:sp><p:spPr><a:gradFill><a:gsLst/></a:gradFill></p:spPr><p:txBody><a:p><a:r><a:t>Read me</a:t></a:r></a:p></p:txBody></p:sp>"
    assert any("1.4.3" in x["wcag"] for x in os_.pptx_complex_bg_contrast_checks(_pptx(tmp_path, sp)))


def test_pptx_text_over_solid_fill_not_flagged(tmp_path):
    sp = '<p:sp><p:spPr><a:solidFill><a:srgbClr val="FFFFFF"/></a:solidFill></p:spPr><p:txBody><a:p><a:r><a:t>Read me</a:t></a:r></a:p></p:txBody></p:sp>'
    assert os_.pptx_complex_bg_contrast_checks(_pptx(tmp_path, sp)) == []


def test_pptx_picture_shape_without_text_not_flagged(tmp_path):
    sp = "<p:sp><p:spPr><a:blipFill><a:blip/></a:blipFill></p:spPr><p:txBody><a:p/></p:txBody></p:sp>"
    assert os_.pptx_complex_bg_contrast_checks(_pptx(tmp_path, sp)) == []


# ── dispatcher wiring + robustness ────────────────────────────────────────────
def test_checks_for_routes_tier_a(tmp_path):
    docx = _docx(tmp_path, f"<w:tbl><w:tblGrid>{_cols(10)}</w:tblGrid></w:tbl>")
    assert any(x["wcag"].startswith("1.4.10") for x in os_.checks_for(docx, ".docx"))
    sp = "<p:sp><p:spPr><a:gradFill/></p:spPr><p:txBody><a:p><a:r><a:t>Hi</a:t></a:r></a:p></p:txBody></p:sp>"
    scs = {x["wcag"] for x in os_.checks_for(_pptx(tmp_path, sp), ".pptx")}
    assert any(w.startswith("1.4.3") for w in scs)


def test_corrupt_zip_never_raises(tmp_path):
    p = tmp_path / "bad.docx"
    p.write_bytes(b"not a zip")
    assert os_.office_reflow_checks(p, ".docx") == []
    assert os_.office_text_spacing_checks(p, ".docx") == []
    assert os_.pptx_resize_text_checks(p) == []
    assert os_.pptx_complex_bg_contrast_checks(p) == []
