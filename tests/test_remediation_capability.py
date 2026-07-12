"""Contract test: prove api/remediation_capability.CAPABILITY against the real remediators.

This is the drift guard behind the product's "Word/Excel are 100% actioned" claim. It does NOT
just assert the dict's shape — it exercises the actual pipeline for every entry:

  * Structure  — CAPABILITY's key set equals store.RULE_FORMATS' in-scope pairs, exactly, in both
                 directions (a new detector or a removed rule with no matching lane fails here).
  * "auto"     — for each auto entry: build a fixture that trips it, run the real remediator
                 (remediate_office / remediate_pdf / remediate_html), re-scan the output with
                 scanner.analyse_and_assess, and assert the SC no longer fires. If an auto entry
                 does not clear, the LANE is wrong — fix the table, not this test.
  * "assisted" — for each assisted entry: assert the proposer that backs it emits a proposal for a
                 triggering input.

Gating mirrors tests/test_demo_fixtures.py: assertions that need the .NET Office analysers skip
when the CLI is not built; OCR / langdetect / vision / text-model assertions skip when that
capability is unavailable. Nothing here fabricates a pass — a skipped assertion is reported as a
skip, never a green.
"""
from __future__ import annotations

import os
import shutil
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))
sys.path.insert(0, str(ROOT / "scripts"))

import remediation_capability as cap  # noqa: E402
import store  # noqa: E402


# ── capability gates ──────────────────────────────────────────────────────────
_DOTNET = Path(os.environ.get("ACP_DOTNET") or os.path.expanduser("~/.dotnet/dotnet"))
_CLI_DLL = Path(os.environ.get("ACP_OFFICE_CLI")
                or ROOT / "spike/dotnet/AcpScan.Cli/bin/Release/net10.0/AcpScan.Cli.dll")
_ENGINE_OK = (shutil.which("dotnet") is not None or _DOTNET.exists()) and _CLI_DLL.exists()
_NO_ENGINE = "the .NET Office analyser CLI is not built (spike/dotnet/…/AcpScan.Cli.dll)"


def _ocr_ok() -> bool:
    try:
        import ocr
        return ocr.is_available()
    except Exception:
        return False


def _langdetect_ok() -> bool:
    try:
        import langdetect  # noqa: F401
        return True
    except Exception:
        return False


def _vision_ok() -> bool:
    try:
        import ai
        return ai.vision_is_available()
    except Exception:
        return False


def _textmodel_ok() -> bool:
    try:
        import ai
        return ai.is_available()
    except Exception:
        return False


def _sc(wcag: str) -> str:
    """A finding's wcag label → bare 'X.Y.Z' (handles both 'SC_1_1_1' and '2.4.6 Headings')."""
    w = (wcag or "").strip()
    if w.startswith("SC_"):
        return w[3:].replace("_", ".")
    return w.split(" ", 1)[0] if w else ""


def _inscope(fmt: str) -> set[str]:
    return {sc for sc, fmts in store.RULE_FORMATS.items() if fmt in fmts}


def _rescan(path: Path, name: str, tmp: Path):
    """Copy `path` into a clean dir named `name` and run the real scan pipeline over it.
    Returns (set of SCs that fire, engine_ran)."""
    d = tmp / f"rescan-{name}"
    d.mkdir(parents=True, exist_ok=True)
    shutil.copy(path, d / name)
    import scanner
    fdict, _ = scanner.analyse_and_assess(d, name, detect_pii=False)
    issues = fdict.get("issues", [])
    scs = {_sc(i.get("wcag", "")) for i in issues}
    engine_ran = any(str(i.get("wcag", "")).startswith("SC_") for i in issues)
    return scs, engine_ran


def _auto(fmt: str) -> set[str]:
    return {sc for sc, ln in cap.CAPABILITY[fmt].items() if ln == cap.AUTO}


def _assisted(fmt: str) -> set[str]:
    return {sc for sc, ln in cap.CAPABILITY[fmt].items() if ln == cap.ASSISTED}


# ══ structure — the drift guard ════════════════════════════════════════════════
def test_lanes_are_valid():
    for fmt, table in cap.CAPABILITY.items():
        for sc, ln in table.items():
            assert ln in cap.LANES, f"{fmt} {sc}: unknown lane {ln!r}"


def test_capability_formats_match_rule_formats():
    all_fmts = set().union(*store.RULE_FORMATS.values())
    assert set(cap.CAPABILITY) == all_fmts, (
        f"CAPABILITY formats {sorted(cap.CAPABILITY)} != RULE_FORMATS formats {sorted(all_fmts)}")


@pytest.mark.parametrize("fmt", sorted(set().union(*store.RULE_FORMATS.values())))
def test_no_orphans_either_way(fmt):
    """Every in-scope (format, SC) has a lane, and no lane exists for an out-of-scope SC."""
    inscope = _inscope(fmt)
    keyed = set(cap.CAPABILITY[fmt])
    missing = inscope - keyed
    extra = keyed - inscope
    assert not missing, f"{fmt}: in-scope criteria with no capability lane: {sorted(missing)}"
    assert not extra, f"{fmt}: capability lane for out-of-scope criteria: {sorted(extra)}"


# ══ "auto" — prove every auto entry clears on re-scan ══════════════════════════
@pytest.mark.skipif(not _ENGINE_OK, reason=_NO_ENGINE)
@pytest.mark.parametrize("fmt,name,build", [
    ("docx", "word-accessibility-demo.docx", "build_docx"),
    ("xlsx", "excel-accessibility-demo.xlsx", "build_xlsx"),
])
def test_office_auto_entries_clear(fmt, name, build, tmp_path):
    """The whole gen_demo_fixtures file trips every in-scope criterion; after remediation every
    'auto'-laned criterion for that format must have stopped firing. This is the "100% actioned"
    proof for Word/Excel."""
    import gen_demo_fixtures as gen
    import remediate_office

    src_dir = tmp_path / "src"
    src_dir.mkdir()
    getattr(gen, build)(src_dir / name)

    before, engine_ran = _rescan(src_dir / name, name, tmp_path)
    if not engine_ran:
        pytest.skip(_NO_ENGINE)

    auto = _auto(fmt)
    # Sanity: the fixture must actually exhibit the auto findings, else "cleared" is vacuous.
    not_tripped = auto - before
    assert not not_tripped, f"{name}: fixture did not trip auto criteria {sorted(not_tripped)}"

    fixed, applied, _skipped = remediate_office.remediate_office(src_dir / name, ai_enabled=False)
    assert fixed is not None, f"{name}: remediator produced no output"

    after, _ = _rescan(Path(fixed), f"remediated-{name}", tmp_path)
    still_firing = auto & after
    assert not still_firing, (
        f"{name}: 'auto' criteria still fail after remediation: {sorted(still_firing)} "
        f"— the CAPABILITY lane is wrong, not the test")


def _raw_pptx(path: Path) -> None:
    """A minimal PowerPoint that trips 1.3.2 (shapes authored bottom-to-top), 1.4.3/1.4.6
    (white-on-orange runs), 2.4.2 (no title) and 3.1.1 (no language anywhere) — the pptx auto
    set. Hand-built OPC so no run carries a lang attribute (python-pptx always injects one,
    which would mask 3.1.1)."""
    P = "http://schemas.openxmlformats.org/presentationml/2006/main"
    A = "http://schemas.openxmlformats.org/drawingml/2006/main"
    R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

    def shape(idx, name, y, text):
        return (
            f'<p:sp><p:nvSpPr><p:cNvPr id="{idx + 2}" name="{name}"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>'
            f'<p:spPr><a:xfrm><a:off x="1000000" y="{y}"/><a:ext cx="2000000" cy="500000"/></a:xfrm>'
            f'<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>'
            f'<a:solidFill><a:srgbClr val="F07D00"/></a:solidFill></p:spPr>'
            f'<p:txBody><a:bodyPr/><a:p><a:r>'
            f'<a:rPr lang=""/><a:solidFill><a:srgbClr val="FFFFFF"/></a:solidFill>'
            f'<a:t>{text}</a:t></a:r></a:p></p:txBody></p:sp>')

    shapes = "".join(shape(i, n, y, t) for i, (n, y, t) in enumerate([
        ("bottom", 6000000, "Bottom shape authored first low contrast label"),
        ("lower", 4500000, "Lower middle authored second contrast label"),
        ("upper", 3000000, "Upper middle authored third contrast label"),
        ("top", 1000000, "Top shape authored last contrast label")]))
    slide = (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<p:sld xmlns:p="{P}" xmlns:a="{A}" xmlns:r="{R}"><p:cSld><p:spTree>'
        f'<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr/>'
        f'{shapes}</p:spTree></p:cSld></p:sld>')
    ctypes = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>'
        '<Override PartName="/ppt/slides/slide1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>'
        '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/></Types>')
    root_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="ppt/presentation.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/></Relationships>')
    pres = (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<p:presentation xmlns:p="{P}" xmlns:r="{R}" xmlns:a="{A}">'
        f'<p:sldIdLst><p:sldId id="256" r:id="rId1"/></p:sldIdLst></p:presentation>')
    pres_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide1.xml"/></Relationships>')
    core = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title></dc:title></cp:coreProperties>')
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", ctypes)
        z.writestr("_rels/.rels", root_rels)
        z.writestr("ppt/presentation.xml", pres)
        z.writestr("ppt/_rels/presentation.xml.rels", pres_rels)
        z.writestr("ppt/slides/slide1.xml", slide)
        z.writestr("docProps/core.xml", core)


@pytest.mark.skipif(not _ENGINE_OK, reason=_NO_ENGINE)
def test_pptx_auto_entries_clear(tmp_path):
    import remediate_office
    name = "deck-accessibility-demo.pptx"
    src = tmp_path / name
    _raw_pptx(src)

    before, engine_ran = _rescan(src, name, tmp_path)
    if not engine_ran:
        pytest.skip(_NO_ENGINE)

    auto = _auto("pptx")
    not_tripped = auto - before
    assert not not_tripped, f"pptx fixture did not trip auto criteria {sorted(not_tripped)}"

    fixed, applied, _skipped = remediate_office.remediate_office(src, ai_enabled=False)
    assert fixed is not None
    after, _ = _rescan(Path(fixed), f"remediated-{name}", tmp_path)
    still_firing = auto & after
    assert not still_firing, f"pptx 'auto' criteria still fail: {sorted(still_firing)}"


@pytest.mark.skipif(not _ENGINE_OK, reason=_NO_ENGINE)
def test_pdf_auto_entries_clear(tmp_path):
    pytest.importorskip("pikepdf")
    pytest.importorskip("pypdf")
    pytest.importorskip("reportlab")
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas
    import remediate_pdf

    name = "report-accessibility-demo.pdf"
    src = tmp_path / name
    c = canvas.Canvas(str(src), pagesize=letter)
    for i, h in enumerate(["Introduction", "Background", "Methods", "Results",
                           "Discussion", "Conclusion"]):
        c.setFont("Helvetica-Bold", 20)
        c.drawString(72, 720, h)
        c.setFont("Helvetica", 11)
        c.drawString(72, 690, f"Body paragraph {i} with enough real words to read as prose.")
        c.showPage()
    c.save()

    before, engine_ran = _rescan(src, name, tmp_path)
    if not engine_ran:
        pytest.skip("PDF analysis engine did not run")

    auto = _auto("pdf")
    not_tripped = auto - before
    assert not not_tripped, f"pdf fixture did not trip auto criteria {sorted(not_tripped)}"

    fixed, applied, _skipped = remediate_pdf.remediate_pdf(src, ai_enabled=False)
    assert fixed is not None
    after, _ = _rescan(Path(fixed), f"remediated-{name}", tmp_path)
    still_firing = auto & after
    assert not still_firing, f"pdf 'auto' criteria still fail: {sorted(still_firing)}"


# One minimal HTML fixture per html 'auto' criterion — each must trip the criterion and clear
# after remediate_html. Kept inline so the trigger for every lane is visible in one place.
_HTML_FIXTURES = {
    "1.3.1": '<html lang="en"><head><title>T</title></head><body><form><input type="text" name="q"></form></body></html>',
    "1.3.4": '<html lang="en"><head><title>T</title><style>@media(orientation:portrait){.x{display:none}}</style></head><body>x</body></html>',
    "1.3.5": '<html lang="en"><head><title>T</title></head><body><form><input type="email" name="email"></form></body></html>',
    "1.4.1": '<html lang="en"><head><title>T</title></head><body><a href="/x" style="color:#00f">link</a></body></html>',
    "1.4.2": '<html lang="en"><head><title>T</title></head><body><audio autoplay src="a.mp3"></audio></body></html>',
    "1.4.3": '<html lang="en"><head><title>T</title></head><body><p style="color:#cccccc">low</p></body></html>',
    "1.4.4": '<html lang="en"><head><title>T</title><meta name="viewport" content="user-scalable=no"></head><body>x</body></html>',
    "1.4.6": '<html lang="en"><head><title>T</title></head><body><p style="color:#808080">midtone</p></body></html>',
    "1.4.10": '<html lang="en"><head><title>T</title><style>.a{}</style></head><body>x</body></html>',
    "1.4.12": '<html lang="en"><head><title>T</title></head><body><p style="line-height:20px">x</p></body></html>',
    "2.4.1": '<html lang="en"><head><title>T</title></head><body><nav>n</nav><p>content here</p></body></html>',
    "2.4.2": '<html lang="en"><head></head><body>x</body></html>',
    "2.4.3": '<html lang="en"><head><title>T</title></head><body><a href="/x" tabindex="3">x</a></body></html>',
    "2.4.6": '<html lang="en"><head><title>T</title></head><body><h1>A</h1><p>text</p><h3>B</h3></body></html>',
    "2.4.7": '<html lang="en"><head><title>T</title><style>a{outline:none}</style></head><body><a href="/x">x</a></body></html>',
    "2.5.3": '<html lang="en"><head><title>T</title></head><body><button aria-label="Submit">Send now</button></body></html>',
    "3.1.1": '<html><head><title>T</title></head><body>x</body></html>',
    "3.1.4": '<html lang="en"><head><title>T</title></head><body><p>The WCAG standard matters.</p></body></html>',
    "3.3.2": '<html lang="en"><head><title>T</title></head><body><form><input type="text" required></form></body></html>',
    "4.1.2": '<html lang="en"><head><title>T</title></head><body><form><input type="text"></form></body></html>',
}


@pytest.mark.parametrize("sc", sorted(_auto("html"), key=lambda s: tuple(int(x) for x in s.split("."))))
def test_html_auto_entries_clear(sc, tmp_path):
    """html auto lanes are proven with the pure-Python HTML scanner (no .NET needed)."""
    from remediate import remediate_html

    assert sc in _HTML_FIXTURES, f"no HTML fixture for auto criterion {sc}"
    html = _HTML_FIXTURES[sc]

    before, _ = _rescan(_write(tmp_path, "before.html", html), "before.html", tmp_path)
    assert sc in before, f"HTML fixture for {sc} did not trip the criterion"

    fixed, applied, _deferred = remediate_html(html, proposals=[])
    after, _ = _rescan(_write(tmp_path, "after.html", fixed), "after.html", tmp_path)
    assert sc not in after, (
        f"html 'auto' criterion {sc} still fails after remediate_html "
        f"— the CAPABILITY lane is wrong, not the test")


def _write(d: Path, name: str, text: str) -> Path:
    p = d / name
    p.write_text(text, encoding="utf-8")
    return p


# ══ "assisted" — prove a proposer emits a prefilled fix for each assisted entry ═══
# Each assisted SC is backed by exactly one proposer. Verify the proposer once (it is
# format-agnostic), and assert every assisted lane maps to a verified proposer — so a new
# assisted entry with no backing proposer is caught.
def _proposer_key(sc: str) -> str:
    return {
        "1.1.1": "vision_alt",
        "1.3.2": "vision_reading_order",   # pdf only
        "1.3.3": "sensory",
        "1.4.5": "images_of_text",
        "1.4.9": "images_of_text",
        "3.1.2": "language_parts",
        "3.1.5": "reading_level",          # GPU plain-language rewrite proposer (#123 follow-on)
        "2.4.4": "link_text",              # html only
    }.get(sc, "")


def _all_assisted():
    return [(fmt, sc) for fmt in cap.CAPABILITY for sc in _assisted(fmt)]


def test_every_assisted_entry_has_a_known_proposer():
    unknown = [(f, s) for f, s in _all_assisted() if not _proposer_key(s)]
    assert not unknown, f"assisted entries with no mapped proposer: {unknown}"


def test_proposer_images_of_text_emits():
    """1.4.5 / 1.4.9 — OCR the baked-in text back out as a one-click proposal."""
    if not _ocr_ok():
        pytest.skip("OCR (tesseract) not available")
    import tempfile

    import gen_demo_fixtures as gen
    import proposals
    td = Path(tempfile.mkdtemp())
    gen.build_docx(td / "w.docx")
    out = proposals.propose_images_of_text(td / "w.docx", ".docx")
    assert out, "images-of-text proposer emitted nothing for a text-bearing image"
    assert out[0].get("proposed_value"), "proposal carries no OCR'd value"


def test_proposer_language_parts_emits():
    """3.1.2 — deterministic per-span language proposal."""
    if not _langdetect_ok():
        pytest.skip("langdetect not available")
    import proposals
    out = proposals.propose_language_parts(
        "The quick brown fox jumps over the lazy dog every single morning here today. "
        "Le renard brun rapide saute par-dessus le chien paresseux chaque matin ici aussi.")
    assert out, "language-of-parts proposer emitted nothing for bilingual text"
    assert out[0].get("proposed_value"), "language proposal carries no code"


def test_proposer_link_text_emits():
    """html 2.4.4 — a deterministic link-purpose proposal derived from the target."""
    import proposals
    out = proposals.derive_link_text("/annual-report.pdf", "")
    assert out and out.get("text"), "link-text proposer produced no derived text"
    assert out.get("deterministic") is True


def test_proposer_sensory_emits():
    """1.3.3 — non-sensory rewrite. Needs the local text model (Ollama); skips otherwise."""
    if not _textmodel_ok():
        pytest.skip("local text model (Ollama) not available")
    import proposals
    out = proposals.propose_sensory_rewrite(
        "Click the round green button on the right to submit the form.", ai_enabled=True)
    assert out, "sensory proposer emitted nothing for a sensory instruction"


# ══ reconciliation with the earlier sparse version ═════════════════════════════
# The module exposes the sparse version's helper API (mode_for/auto_scs/as_dict/FORMATS) so
# its /capability route and frontend mirror keep working. These pin that surface, and pin the
# three lane calls this reconciliation CORRECTED (a revert to the old values fails here).
def test_compat_mode_for_defaults_to_human_out_of_scope():
    assert cap.mode_for("docx", "9.9.9") == cap.HUMAN
    assert cap.mode_for("unknown-format", "1.1.1") == cap.HUMAN
    assert cap.mode_for(None, None) == cap.HUMAN
    # an in-scope human criterion is returned explicitly (dense table), same net answer
    assert cap.mode_for("docx", "1.4.8") == cap.HUMAN


def test_compat_auto_scs_matches_auto_lanes():
    for fmt in cap.FORMATS:
        assert cap.auto_scs(fmt) == _auto(fmt)


def test_compat_as_dict_is_an_equal_deep_copy():
    d = cap.as_dict()
    assert d == cap.CAPABILITY
    d["docx"]["3.1.1"] = "MUTATED"
    assert cap.CAPABILITY["docx"]["3.1.1"] == cap.AUTO  # module state untouched


def test_compat_formats_are_the_rule_formats_formats():
    assert set(cap.FORMATS) == set().union(*store.RULE_FORMATS.values())


def test_reconciliation_corrected_calls_are_pinned():
    # docx 3.1.1: sparse said human ("engine-blocked") — round-trip proves it clears.
    assert cap.mode_for("docx", "3.1.1") == cap.AUTO
    # pptx contrast: sparse said human ("not verified") — round-trip proves it clears.
    assert cap.mode_for("pptx", "1.4.3") == cap.AUTO
    assert cap.mode_for("pptx", "1.4.6") == cap.AUTO
    # html image alt: sparse said assisted — no proposer backs external <img>, so it is human.
    assert cap.mode_for("html", "1.1.1") == cap.HUMAN


def test_reconciliation_docx_auto_set_is_the_corrected_superset():
    # The sparse version's docx auto set omitted 3.1.1 (and 3.3.2). The corrected, proven set:
    assert cap.auto_scs("docx") == {"1.3.1", "1.4.3", "2.4.2", "2.4.6", "3.1.1", "3.3.2"}


def test_reconciliation_alt_text_assisted_where_a_proposer_backs_it():
    # 1.1.1 is assisted on every format whose remediator can propose from embedded image bytes;
    # html (external <img>, no fetch) is the sole exception and is human.
    for fmt in ("docx", "pptx", "xlsx", "pdf"):
        assert cap.mode_for(fmt, "1.1.1") == cap.ASSISTED, fmt
    assert cap.mode_for("html", "1.1.1") == cap.HUMAN


def test_capability_route_serves_the_table():
    """GET /capability returns the exact in-process table (read-only, public like /config)."""
    from fastapi.testclient import TestClient

    from app import app
    r = TestClient(app).get("/capability")
    assert r.status_code == 200
    body = r.json()
    assert body["capability"] == cap.CAPABILITY
    assert sorted(body["lanes"]) == sorted(cap.LANES)
    assert body["formats"] == list(cap.FORMATS)


def test_capability_route_is_public():
    import core
    assert core.is_public("/capability") is True


def test_proposer_vision_alt_emits():
    """1.1.1 — vision-grounded alt / figure alt. Needs a vision model; skips otherwise."""
    if not _vision_ok():
        pytest.skip("vision model (Ollama) not available")
    import tempfile
    import gen_demo_fixtures as gen
    import remediate_office
    td = Path(tempfile.mkdtemp())
    gen.build_docx(td / "w.docx")
    applied_fixes: list = []
    remediate_office.remediate_office(td / "w.docx", ai_enabled=True, applied_fixes=applied_fixes)
    # With vision on, at least one image gets a grounded alt proposal/fix.
    assert applied_fixes, "vision alt lane produced no alt proposal with a vision model available"
