"""The ACR export as a PDF, checked the way a screen reader would meet it.

NOT "is there a structure tree". That question has a green answer for a document with nothing in
it: `api/report.py::_tag_pdf` bolts an EMPTY /StructTreeRoot onto untagged ReportLab output and
passes ACP's own `pdf.tagged` rule to this day. So the checks below walk the real tree and ask
what a reader would actually get — a title the reader announces, a declared language, marked
content, and the table headers that make 55 rows of conformance data navigable instead of a wall
of cells.

THE NON-VACUITY TEST IS THE LOAD-BEARING ONE. Every structural assertion here is also run against
the SAME html rendered WITHOUT `pdf_variant="pdf/ua-1"`, and must fail. Measured with veraPDF
1.30.2 on this repo's own 55-criterion export:

    write_pdf()                        → NOT conformant, 987 failed checks
    write_pdf(pdf_variant="pdf/ua-1")  → conformant, 0 failed checks

One flag is the entire difference between a conformance document and a picture of one, and it is
the kind of argument a future refactor drops without noticing. A suite that only ever sees the
conformant output cannot tell "this PDF is tagged" from "this assertion never fails".

veraPDF IS THE OTHER HALF, not a substitute: it answers "is this PDF/UA-1", and says nothing
about whether the table headers survived. It is also not installed by the suite (a 33 MB Java
application), so every check that does not need it runs without it.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

pikepdf = pytest.importorskip("pikepdf")
pytest.importorskip("weasyprint")

import acr_catalog  # noqa: E402
import acr_export_pdf  # noqa: E402
import acr_export_preview  # noqa: E402
from verapdf import NO_VERAPDF, VERAPDF_OK, validate  # noqa: E402

OWNER = "owner@acp.test"
ANALYST = "analyst@acp.test"

REPORT = {
    "report_id": "acr_pdftest0001",
    "report_title": "ACP Web UI — Accessibility Conformance Report",
    "product_name": "ACP",
    "product_version": "2026.9.1",
    "build_id": "0f096be0",
    "wcag_version": "2.2",
    "status": "draft",
}


def _criteria(decided: int = 12) -> list[dict]:
    """The REAL applicable matrix, with some rows decided.

    Real, not a handful of invented dicts: the pagination, the running header and the tag count
    are all properties of a table with ~55 rows, and a three-row fixture would demonstrate none
    of them. Some rows are decided so the conformance column is not one repeated cell.
    """
    rows = acr_catalog.build_matrix(REPORT["report_id"])
    finals = sorted(acr_catalog.FINAL_STATUSES)
    for i, c in enumerate(rows[:decided]):
        c["final_status"] = finals[i % len(finals)]
        c["remarks"] = f"Verified against build {REPORT['build_id']}."
    return rows


@pytest.fixture(scope="module")
def html() -> str:
    return acr_export_preview.to_html(
        acr_export_preview.project(REPORT, _criteria(), evidence_by_criterion={}, stale_ids=set()))


@pytest.fixture(scope="module")
def tagged(html) -> bytes:
    return acr_export_pdf.render_html(html)


@pytest.fixture(scope="module")
def untagged(html) -> bytes:
    """The same content with the one flag removed — the control for every check below."""
    import weasyprint
    return weasyprint.HTML(string=html).write_pdf()


# ── what the structure actually carries ───────────────────────────────────────

def _open(data: bytes):
    import io
    return pikepdf.open(io.BytesIO(data))


def _struct_kids(pdf) -> int:
    root = pdf.Root.get("/StructTreeRoot")
    if root is None:
        return 0
    kids = root.get("/K")
    if kids is None:
        return 0
    return len(kids) if isinstance(kids, pikepdf.Array) else 1


def _pdf_text(data: bytes) -> str:
    import io

    import pdfplumber
    with pdfplumber.open(io.BytesIO(data)) as doc:
        return "\n".join((p.extract_text() or "") for p in doc.pages)


def _tag_counts(pdf) -> dict:
    """Every structure element type in the tree, counted. Keyed on objgen, NOT id(node).

    pikepdf returns a fresh wrapper per access and CPython recycles addresses, so an id-keyed
    walk truncates the tree and under-reports — #1159 hit exactly this and read 2 headings on a
    document holding 5.
    """
    from collections import Counter
    counts: Counter = Counter()
    seen: set = set()
    root = pdf.Root.get("/StructTreeRoot")
    if root is None:
        return {}

    def walk(node):
        try:
            key = node.objgen
        except AttributeError:
            key = None
        if key and key != (0, 0):
            if key in seen:
                return
            seen.add(key)
        if isinstance(node, pikepdf.Dictionary):
            s = node.get("/S")
            if s is not None:
                counts[str(s).lstrip("/")] += 1
            kids = node.get("/K")
            if kids is not None:
                walk(kids)
        elif isinstance(node, pikepdf.Array):
            for k in node:
                walk(k)

    walk(root)
    return dict(counts)


def test_the_fixture_is_a_real_matrix_not_a_toy():
    """The premise. A three-row table would demonstrate none of what is asserted below."""
    rows = _criteria()
    assert len(rows) >= 40, f"only {len(rows)} criteria — this is not the applicable matrix"


def test_the_pdf_declares_a_structure_tree_that_is_not_empty(tagged):
    with _open(tagged) as pdf:
        assert _struct_kids(pdf) > 0, (
            "no structure tree, or an empty one — an empty /StructTreeRoot passes ACP's own "
            "pdf.tagged rule and gives a screen-reader user nothing")


def test_the_content_is_marked(tagged):
    with _open(tagged) as pdf:
        mark = pdf.Root.get("/MarkInfo")
        assert mark is not None and bool(mark.get("/Marked")), (
            "/MarkInfo /Marked is absent or false — the page content is not associated with the "
            "structure tree, so the tree describes nothing")


def test_the_document_declares_its_language(tagged):
    with _open(tagged) as pdf:
        lang = pdf.Root.get("/Lang")
        assert lang is not None and str(lang).lower().startswith("en"), (
            f"/Lang is {lang!r} — a reader cannot choose a voice for a document with no language")


def test_a_reader_announces_the_title_not_the_filename(tagged):
    """ISO 14289 §7.1: /DisplayDocTitle. Without it a reader announces "acr-acr_pdftest0001.pdf",
    which is the one string in this whole document that means nothing to the person hearing it."""
    with _open(tagged) as pdf:
        prefs = pdf.Root.get("/ViewerPreferences")
        assert prefs is not None and bool(prefs.get("/DisplayDocTitle")), (
            "/ViewerPreferences /DisplayDocTitle is not set")
        assert str(pdf.docinfo.get("/Title") or "") != "", "the document has no /Title to announce"


def test_the_table_headers_survive_as_real_TH(tagged):
    """The four column meanings and every row's criterion label are <th> in the source. If they
    arrive as TD the table is a grid of anonymous cells and the reader must count columns."""
    with _open(tagged) as pdf:
        counts = _tag_counts(pdf)
    assert counts.get("TH", 0) >= 4, (
        f"expected at least the 4 column headers as TH, got {counts.get('TH', 0)}; tags: {counts}")
    assert counts.get("TD", 0) > 0, f"no TD cells at all — tags: {counts}"


def test_every_criterion_reaches_the_pdf(tagged, html):
    """The honesty constraint that matters most, carried across the renderer: acr_export_preview
    never omits a criterion for being undecided, and the PDF must not quietly lose one either."""
    flat = " ".join(_pdf_text(tagged).split())
    missing = [c["criterion_num"] for c in _criteria() if c["criterion_num"] not in flat]
    assert not missing, f"{len(missing)} criteria are in the preview and not in the PDF: {missing[:8]}"


def test_no_internal_workflow_state_appears_in_the_pdf(tagged):
    """acr_export_preview refuses to print one; this proves the refusal survives rendering."""
    # Whitespace fully normalized, because the renderer wraps INSIDE a phrase: the undecided cell
    # comes out of pdfplumber as "— not yet\nevaluated —". A substring check against un-normalized
    # extract_text() reports a missing string that is on the page, which reads as a product bug.
    text = " ".join(_pdf_text(tagged).split()).lower()
    # The machine tokens only. `decided` is also a WORKFLOW_STATE and also an ordinary English
    # word — asserting on it would fail the day a remark reads "the team decided", which is prose,
    # not a leak. The two below cannot occur except by a state escaping into the rendering.
    leaked = [w for w in ("needs_review", "not_evaluated") if w in text]
    assert not leaked, f"internal workflow state(s) rendered into the conformance report: {leaked}"
    # And the undecided cell, which IS allowed, must still be the deliberately non-VPAT-shaped
    # one — a reader must not be able to mistake it for a fifth conformance term.
    assert "not yet evaluated" in text, (
        "no undecided cell reached the PDF, so this test did not exercise the path where an "
        "internal state could have leaked")


# ── the control: none of the above may pass without the variant flag ──────────

@pytest.mark.parametrize("check,label", [
    (lambda pdf: _struct_kids(pdf) > 0, "structure tree"),
    (lambda pdf: bool((pdf.Root.get("/MarkInfo") or {}).get("/Marked")), "/MarkInfo /Marked"),
    (lambda pdf: bool((pdf.Root.get("/ViewerPreferences") or {}).get("/DisplayDocTitle")),
     "/DisplayDocTitle"),
    (lambda pdf: _tag_counts(pdf).get("TH", 0) >= 4, "TH cells"),
])
def test_the_same_html_without_the_variant_flag_fails_this_check(untagged, check, label):
    """If any of these passes on the untagged control, the corresponding assertion above is
    measuring nothing — it would stay green on a PDF that lost its tagging entirely."""
    with _open(untagged) as pdf:
        assert not check(pdf), (
            f"{label} is present WITHOUT pdf_variant='pdf/ua-1' — so the test that asserts it on "
            f"the tagged output cannot detect the flag being dropped")


def test_the_renderer_actually_passes_the_variant(monkeypatch, html):
    """Pins the flag itself. The control above proves it matters; this catches it going missing
    even if some future WeasyPrint tags by default and the control silently stops biting."""
    import weasyprint
    seen = {}
    real = weasyprint.HTML.write_pdf

    def spy(self, *a, **kw):
        seen.update(kw)
        return real(self, *a, **kw)

    monkeypatch.setattr(weasyprint.HTML, "write_pdf", spy)
    acr_export_pdf.render_html(html)
    assert seen.get("pdf_variant") == "pdf/ua-1", f"write_pdf called with {seen}"


# ── veraPDF: the standard's own answer ────────────────────────────────────────

@pytest.mark.skipif(not VERAPDF_OK, reason=NO_VERAPDF)
def test_verapdf_says_the_export_is_pdf_ua_1(tagged, tmp_path):
    p = tmp_path / "acr.pdf"
    p.write_bytes(tagged)
    result = validate(p)
    assert result.compliant, result.summary()
    assert result.failed_checks == 0, result.summary()


@pytest.mark.skipif(not VERAPDF_OK, reason=NO_VERAPDF)
def test_verapdf_rejects_the_untagged_control(untagged, tmp_path):
    """"veraPDF says PASS" is only evidence if veraPDF can say FAIL on this same content."""
    p = tmp_path / "untagged.pdf"
    p.write_bytes(untagged)
    result = validate(p)
    assert not result.compliant, (
        "veraPDF passed an untagged render of the same page — the validator is not judging what "
        "this suite thinks it is")


# ── the download itself ───────────────────────────────────────────────────────

def test_an_absent_weasyprint_raises_rather_than_returning_something(html, monkeypatch):
    """The fail-closed rule AT THE LEVEL IT IS IMPLEMENTED.

    The route test below proves the 503 by stubbing `render_html` to raise — which never
    exercises the import guard inside it. A bite check found that gap: replacing the guard's
    `raise` with `return b"%PDF-1.7\\n"` left all 20 tests passing, so "fail closed on a missing
    renderer" was an untested claim about the one path that only runs on a broken deployment,
    where nobody is watching.
    """
    monkeypatch.setitem(sys.modules, "weasyprint", None)   # makes `import weasyprint` raise
    with pytest.raises(acr_export_pdf.RendererUnavailable) as exc:
        acr_export_pdf.render_html(html)
    assert "weasyprint" in str(exc.value).lower()


def test_is_available_reports_the_same_thing_render_would_do(monkeypatch, html):
    """A caller that asks before offering a download must get the answer rendering would give.
    If these disagree the UI offers a button that always fails, or hides one that would work."""
    assert acr_export_pdf.is_available() is True
    monkeypatch.setitem(sys.modules, "weasyprint", None)
    assert acr_export_pdf.is_available() is False


def test_the_filename_names_the_report():
    # BOTH SPELLINGS OF THE ID. The store row calls it `id` (the acr_report primary key) and the
    # projection calls it `report_id`; the route hands over the store row. Asserting only the
    # second is how this shipped naming every report `acr-report.pdf` on the first run.
    assert acr_export_pdf.filename_for({"id": "acr_abc123"}) == "acr-acr_abc123.pdf"
    assert acr_export_pdf.filename_for({"report_id": "acr_abc123"}) == "acr-acr_abc123.pdf"
    assert acr_export_pdf.filename_for({"id": "acr_abc123", "revision": 3}) == \
        "acr-acr_abc123-rev3.pdf"
    assert "/" not in acr_export_pdf.filename_for({"id": "../../etc/passwd"})
    assert acr_export_pdf.filename_for({}) == "acr-report.pdf"


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
    monkeypatch.setattr(core, "email_allowed", lambda e: e in (OWNER, ANALYST))

    c = TestClient(app)

    def as_user(email):
        c.headers.update({"Authorization": f"Bearer {email}"})
        return c
    return as_user


@pytest.fixture()
def report_id(client):
    return client(OWNER).post("/acr", json={"product_version": "2026.9.1",
                                            "build_id": "0f096be0"}).json()["report_id"]


def test_a_user_can_generate_and_download_the_accessible_report(client, report_id):
    """End to end, over HTTP, as a person actually does it: ask for the PDF, get a PDF back, and
    have it be the tagged one. Each half has been shipped without the other — a route that
    returns application/pdf proves nothing about the bytes, and a renderer with no route reaches
    nobody."""
    r = client(ANALYST).get(f"/acr/{report_id}/preview", params={"format": "pdf"})
    assert r.status_code == 200, r.text[:300]
    assert r.headers["content-type"].startswith("application/pdf"), r.headers["content-type"]

    disp = r.headers.get("content-disposition", "")
    assert "attachment" in disp and report_id in disp, disp

    body = r.content
    assert body.startswith(b"%PDF-"), body[:20]
    with _open(body) as pdf:
        assert _struct_kids(pdf) > 0, "the downloaded file is not a tagged PDF"
        assert bool((pdf.Root.get("/ViewerPreferences") or {}).get("/DisplayDocTitle"))


def test_the_pdf_and_the_html_preview_cannot_disagree(client, report_id):
    """Both formats come from ONE project() call in the route. This asserts the consequence a
    reviewer depends on: what they approved on screen is what the customer receives."""
    rows = client(ANALYST).get(f"/acr/{report_id}/preview").json()["criteria"]
    pdf = client(ANALYST).get(f"/acr/{report_id}/preview", params={"format": "pdf"}).content
    text = " ".join(_pdf_text(pdf).split())
    missing = [r["criterion_num"] for r in rows if r["criterion_num"] not in text]
    assert not missing, f"in the JSON projection but not the PDF: {missing[:8]}"


def test_json_and_html_are_unchanged(client, report_id):
    """The new branch must not have moved the two formats that already shipped."""
    j = client(ANALYST).get(f"/acr/{report_id}/preview")
    assert j.status_code == 200 and "criteria" in j.json()
    h = client(ANALYST).get(f"/acr/{report_id}/preview", params={"format": "html"})
    assert h.status_code == 200 and h.headers["content-type"].startswith("text/html")


def test_a_deployment_that_cannot_tag_says_so_instead_of_serving_an_untagged_pdf(
        client, report_id, monkeypatch):
    """The fail-closed rule. An untagged conformance report is indistinguishable from this one to
    everyone except the reader it exists for, so there is no acceptable fallback."""
    def boom(_html):
        raise acr_export_pdf.RendererUnavailable(acr_export_pdf.MISSING_RENDERER)

    monkeypatch.setattr(acr_export_pdf, "render_html", boom)
    r = client(ANALYST).get(f"/acr/{report_id}/preview", params={"format": "pdf"})
    assert r.status_code == 503, r.status_code
    assert "weasyprint" in r.text.lower(), r.text[:300]
    assert not r.content.startswith(b"%PDF-")
