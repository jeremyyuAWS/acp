"""The ACR accessible PDF export, end to end (PRD §16) — wiring #1159's PDF/UA-1 renderer.

WHAT THIS FILE IS FOR. `tests/test_report_weasy_structure.py` proves the RENDERER produces a real
structure tree. This proves the PRODUCT does: that a user can drive the ACR workspace and come
away holding a PDF/UA-1 conformant document, over HTTP, with the right headers to actually
download it.

THE VALIDATION IS NOT OPTIONAL HERE. `tests/verapdf.py` degrades to a skip when veraPDF is absent
— correct on a developer machine, and the wrong thing in CI, where a skipped conformance check is
a compliance claim nothing evaluated. `scripts/install_verapdf.sh` runs as a CI step precisely so
these do not skip there. That is the same rule tests/test_undeclared_importorskip.py enforces for
pip dependencies, applied to the one that has no wheel.

WHAT PASSING HERE DOES NOT MEAN. ADR 0034 conditions the renderer migration on PAC 2024 and a
screen-reader pass; neither has been run. #1159 documents two defects that shipped through 0
veraPDF failures and a green structural suite — the whole report set in serif, and row headers
restyled into a redesign — both caught only by looking at a rendered page. So these tests say the
document is machine-conformant and structurally sound. They do not say a screen-reader user has
read one.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

weasyprint = pytest.importorskip("weasyprint")
pikepdf = pytest.importorskip("pikepdf")

import acr_export_pdf  # noqa: E402
import acr_export_preview  # noqa: E402
from verapdf import NO_VERAPDF, VERAPDF_OK, validate  # noqa: E402

OWNER = "owner@acp.test"
APPROVER = "approver@acp.test"
ANALYST = "analyst@acp.test"


def _projection(**over):
    report = {"report_title": "ACP Accessibility Conformance Report",
              "product_name": "ACP by Movate", "product_version": "1.4.0",
              "vendor_name": "Movate", "revision": 1}
    report.update(over)
    return acr_export_preview.project(
        report,
        [{"criterion_num": "1.4.3", "criterion_name": "Contrast (Minimum)", "level": "AA",
          "principle": "Perceivable", "final_status": "Supports", "remarks": ""},
         {"criterion_num": "2.1.1", "criterion_name": "Keyboard", "level": "A",
          "principle": "Operable", "final_status": "Does Not Support",
          "remarks": "The chart legend cannot be reached by keyboard."}])


@pytest.fixture(scope="module")
def built_pdf(tmp_path_factory):
    pdf = acr_export_pdf.build_acr_pdf(_projection())
    path = tmp_path_factory.mktemp("acrpdf") / "acr.pdf"
    path.write_bytes(pdf)
    return path


# ── the conformance gate ───────────────────────────────────────────────────────

@pytest.mark.skipif(not VERAPDF_OK, reason=NO_VERAPDF)
def test_the_exported_acr_is_pdf_ua_1_conformant(built_pdf):
    """The claim the whole export rests on, measured rather than asserted."""
    result = validate(built_pdf, flavour="ua1")
    assert result.compliant, result.summary()
    assert not result.failure_keys, result.summary()


# ── structure: what a screen-reader user actually gets ─────────────────────────

def test_the_document_has_a_real_structure_tree(built_pdf):
    """`api/report.py::_tag_pdf` fabricates an EMPTY /StructTreeRoot that satisfies ACP's own
    `pdf.tagged` rule and gives a reader nothing. ADR 0034 rules that out, so the test asks for
    content in the tree, not for the key's presence."""
    with pikepdf.open(built_pdf) as pdf:
        assert "/StructTreeRoot" in pdf.Root
        root = pdf.Root["/StructTreeRoot"]
        assert "/K" in root, "the structure tree has no children — an empty tree is a fake tree"


def test_every_table_has_header_cells(built_pdf):
    """A conformance table read cell-by-cell with no headers is unusable. Walks the real tree;
    the visited set is keyed on objgen because pikepdf returns a fresh wrapper per access and an
    id()-keyed walk silently truncates (the bug #1159's structural suite documents)."""
    with pikepdf.open(built_pdf) as pdf:
        seen, tags = set(), []

        def walk(node, depth=0):
            if depth > 60:
                return
            # Dedupe on objgen ONLY for indirect objects. Direct objects all report (0, 0), so a
            # naive objgen-keyed visited set marks the first one seen and then skips every other
            # direct object in the tree — this walk returned ['/Document'] and nothing beneath it.
            # #1159's structural suite documents the mirror-image bug with id(): pikepdf returns a
            # fresh wrapper per access, so an id-keyed walk truncates too. Both fail the same way,
            # by reporting a tree far smaller than the real one rather than by erroring.
            key = getattr(node, "objgen", None)
            if key and key != (0, 0):
                if key in seen:
                    return
                seen.add(key)
            if isinstance(node, pikepdf.Dictionary):
                if "/S" in node:
                    tags.append(str(node["/S"]))
                if "/K" in node:
                    walk(node["/K"], depth + 1)
            elif isinstance(node, pikepdf.Array):
                for child in node:
                    walk(child, depth + 1)

        walk(pdf.Root["/StructTreeRoot"])
        assert "/TH" in tags, f"no header cells in the tree: {sorted(set(tags))}"
        assert "/Table" in tags, f"no table in the tree: {sorted(set(tags))}"
        assert "/H1" in tags, f"no top-level heading: {sorted(set(tags))}"


def test_the_document_declares_its_language(built_pdf):
    """Without /Lang a screen reader guesses the voice, and an English report read by a German
    synthesiser is unusable."""
    with pikepdf.open(built_pdf) as pdf:
        assert str(pdf.Root.get("/Lang", "")).lower().startswith("en")


def test_the_document_has_a_title_and_shows_it(built_pdf):
    """PDF/UA requires a title AND that the viewer display it rather than the filename."""
    with pikepdf.open(built_pdf) as pdf:
        assert pdf.docinfo.get("/Title"), "no document title"
        assert pdf.Root["/ViewerPreferences"]["/DisplayDocTitle"]


def test_the_font_is_the_declared_one_and_not_a_silent_fallback(built_pdf):
    """THE BUG #1159 SHIPPED AND CAUGHT. Its font stack was interpolated through an autoescaping
    Jinja environment and arrived as `font-family: &#34;Liberation Sans&#34;` — invalid CSS,
    silently dropped, every page set in WeasyPrint's default serif.

    Asserted on the EMBEDDED FONT of the built PDF, never on the CSS string: asserting the string
    would have passed the entire time that bug was live.
    """
    with pikepdf.open(built_pdf) as pdf:
        fonts = set()
        for page in pdf.pages:
            for font in (page.get("/Resources", {}).get("/Font", {}) or {}).values():
                fonts.add(str(font.get("/BaseFont", "")))
        assert fonts, "no embedded fonts at all"
        assert any("Liberation" in f for f in fonts), \
            f"the declared face is not embedded — silent serif fallback? {sorted(fonts)}"
        assert not any("Serif" in f or "Times" in f for f in fonts), sorted(fonts)


# ── what the document must SAY ─────────────────────────────────────────────────

def _text(path):
    from pdfminer.high_level import extract_text
    return extract_text(str(path))


def test_the_pdf_states_that_it_is_not_a_vpat(built_pdf):
    """A PDF travels. It is mailed, filed and read far from the application that made it, so a
    disclaimer shown only in the UI is one the reader of the artifact never sees."""
    pytest.importorskip("pdfminer.high_level")
    body = _text(built_pdf)
    assert "not a VPAT" in body or "not the official ITI VPAT" in body, body[:400]


def test_the_pdf_records_the_gates_that_have_not_been_run(built_pdf):
    """The limitation this wiring was authorised with, printed INSIDE the document.

    ADR 0034 conditions the renderer migration on PAC 2024 and a screen-reader pass. Neither has
    been run. A reader holding this PDF is entitled to know that its accessibility is
    machine-validated and not yet human-validated — and to know it from the document, not from a
    PR description they will never see.
    """
    pytest.importorskip("pdfminer.high_level")
    body = _text(built_pdf)
    assert "PAC 2024" in body, body[:600]
    assert "screen-reader pass" in body or "screen reader" in body.lower(), body[:600]
    assert "not sufficient" in body, body[:600]


def test_a_conformance_level_never_appears_only_as_colour(built_pdf):
    """1.4.1 applied to ACP's own deliverable: the level is the cell's TEXT."""
    pytest.importorskip("pdfminer.high_level")
    body = _text(built_pdf)
    assert "Supports" in body
    assert "Does Not Support" in body


# ── the export refuses to build a silently broken document ─────────────────────

def test_the_builder_refuses_when_the_print_stylesheet_did_not_apply():
    """A guard against the exact failure mode above, at build time rather than in review.

    If the preview's <style> block ever stops matching what the swap anchors on, the document
    would render with NO styles and still be perfectly conformant — a PDF/UA-1 pass that is
    unreadable. Better to refuse.
    """
    import acr_export_preview as prev

    original = prev.to_html
    try:
        # No <style> block at all: the swap's own .index() raises ValueError before the explicit
        # RuntimeError below can fire. Both are refusals, and this asserts the refusal rather than
        # a particular exception type — an earlier version of this test named RuntimeError and
        # would have passed while never reaching that branch.
        prev.to_html = lambda projection: (
            "<html lang='en'><head><title>t</title></head><body><h1>x</h1></body></html>")
        with pytest.raises((ValueError, RuntimeError)):
            acr_export_pdf.render_pdf_html(_projection())

        # A <style> block that IS present but whose replacement loses the font stack: this reaches
        # the explicit guard, which is the branch that protects against a conformant-but-unstyled
        # PDF.
        prev.to_html = lambda projection: (
            "<html lang='en'><head><title>t</title><style>body{color:#000}</style></head>"
            "<body><h1>x</h1></body></html>")
        import acr_export_pdf as mod
        saved = mod._PDF_CSS
        try:
            mod._PDF_CSS = "body { color: #000 }"        # no font stack
            with pytest.raises(RuntimeError, match="font stack"):
                mod.render_pdf_html(_projection())
        finally:
            mod._PDF_CSS = saved
    finally:
        prev.to_html = original


# ── end to end over HTTP: generate and download ────────────────────────────────

@pytest.fixture()
def client(monkeypatch, isolated_store):
    import core
    from fastapi.testclient import TestClient
    from app import app

    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setattr(core, "ACCESS_CODE", "", raising=False)
    monkeypatch.setattr(core, "GOOGLE_CLIENT_ID", "test-client-id", raising=False)
    monkeypatch.setattr(core, "E2E_KEY", None, raising=False)
    monkeypatch.setattr(core, "OWNER_EMAIL", OWNER, raising=False)
    monkeypatch.setattr(core, "OPEN_ACCESS", True, raising=False)
    monkeypatch.setattr(core, "verify_gis_token", lambda tok: tok or None)
    monkeypatch.setattr(core, "email_allowed", lambda e: e in (OWNER, APPROVER, ANALYST))

    c = TestClient(app)

    def as_user(email):
        c.headers.update({"Authorization": f"Bearer {email}"})
        return c
    return as_user


def test_a_user_can_generate_and_download_the_accessible_report(client, tmp_path):
    """THE END-TO-END PROOF. Create a report through the API, decide a criterion, then download
    the PDF from the export route and validate the bytes that actually came over the wire.

    Validating the RESPONSE BODY rather than a locally built file is the point: it is the only
    version of this test that would notice the route serving a stale cache, the wrong report, or
    a truncated stream.
    """
    c = client(OWNER)
    rid = c.post("/acr", json={"product_version": "1.4.0", "build_id": "b-900"}).json()["report_id"]
    c.patch(f"/acr/{rid}", json={"fields": {"report_title": "ACP ACR",
                                            "product_name": "ACP by Movate"}})
    c.post(f"/acr/{rid}/criteria/1.4.3/decision",
           json={"final_status": "Does Not Support",
                 "remarks": "The chart legend fails at 2.9:1."})

    r = c.get(f"/acr/{rid}/export.pdf")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/pdf"

    # A download, with a filename that identifies the version — not "acr.pdf" on a reviewer's
    # desktop next to four others.
    disposition = r.headers["content-disposition"]
    assert disposition.startswith("attachment;")
    assert "1.4.0" in disposition and disposition.endswith('.pdf"')

    assert r.content[:5] == b"%PDF-", "the response body is not a PDF"
    out = tmp_path / "downloaded.pdf"
    out.write_bytes(r.content)

    with pikepdf.open(out) as pdf:
        assert "/StructTreeRoot" in pdf.Root
        assert str(pdf.Root.get("/Lang", "")).lower().startswith("en")

    from pdfminer.high_level import extract_text
    body = extract_text(str(out))
    assert "Does Not Support" in body
    assert "2.9:1" in body, "the decision's remarks did not reach the downloaded document"


@pytest.mark.skipif(not VERAPDF_OK, reason=NO_VERAPDF)
def test_the_downloaded_bytes_are_pdf_ua_1_conformant(client, tmp_path):
    """The same download, put through veraPDF. Conformance of the artifact the USER receives —
    not of one built beside it in the test."""
    c = client(OWNER)
    rid = c.post("/acr", json={"product_version": "2.0.0"}).json()["report_id"]
    c.patch(f"/acr/{rid}", json={"fields": {"report_title": "ACP ACR",
                                            "product_name": "ACP by Movate"}})

    r = c.get(f"/acr/{rid}/export.pdf")
    assert r.status_code == 200, r.text
    out = tmp_path / "downloaded.pdf"
    out.write_bytes(r.content)

    result = validate(out, flavour="ua1")
    assert result.compliant, result.summary()


def test_exporting_an_unknown_report_is_a_404(client):
    assert client(OWNER).get("/acr/acr_nope/export.pdf").status_code == 404
