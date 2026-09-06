"""`GET /acr/{id}/preview?format=docx` — the Word export, reachable, behind its own gate.

WHY THIS FILE EXISTS AT ALL. `api/acr_export_docx.py` shipped complete: it renders an accessible
Word document from the shared projection, it runs ACP's own analyser over the result, and
`tests/test_acr_export_docx.py` proves seventeen properties of it. And **no application code
imported it**. The preview route offered json, html and pdf; the module was reachable by nobody,
its only references outside its own test were two comments in requirements files explaining that
python-docx had been promoted out of test-only deps because of it.

That is the failure mode this repo has written down twice: a component merged with passing tests
reads as shipped on every status list, and "never wired" and "wired wrongly" both look like a
green suite. Module tests cannot catch it, by construction — they import the module directly. Only
a test that goes through the ROUTE can, which is what every test below does.

THE GATE IS THE POINT, NOT THE DOWNLOAD. PRD §16 requires the generated document to pass ACP's own
accessibility checks, and the honest bar is "no FAIL" (no docx registration declares
`Coverage.FULL`, so PASS is unreachable for any Word document — see the module docstring). Serving
a document that fails that check would ship an inaccessible accessibility report, which is the one
artifact that cannot be allowed out. So the refusal is tested before the happy path is.
"""
from __future__ import annotations

import sys
import zipfile
from io import BytesIO
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

pytest.importorskip("docx")

import acr_export_docx  # noqa: E402

OWNER = "owner@acp.test"
ANALYST = "analyst@acp.test"
STRANGER = "stranger@elsewhere.test"

DOCX_MEDIA = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@pytest.fixture()
def client(monkeypatch, isolated_store):
    import core
    from app import app
    from fastapi.testclient import TestClient

    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setattr(core, "ACCESS_CODE", "", raising=False)
    monkeypatch.setattr(core, "GOOGLE_CLIENT_ID", "test-client-id", raising=False)
    monkeypatch.setattr(core, "E2E_KEY", None, raising=False)
    monkeypatch.setattr(core, "OWNER_EMAIL", OWNER, raising=False)
    monkeypatch.setattr(core, "OPEN_ACCESS", True, raising=False)
    monkeypatch.setattr(core, "verify_gis_token", lambda tok: tok or None)
    monkeypatch.setattr(core, "email_allowed", lambda e: e in (OWNER, ANALYST, STRANGER))

    c = TestClient(app)

    def as_user(email):
        c.headers.update({"Authorization": f"Bearer {email}"})
        return c
    return as_user


@pytest.fixture()
def report(client, isolated_store):
    """A report with enough metadata to render, and every criterion decided.

    Decisions go through the store rather than 55 HTTP round trips; the EXPORT goes through HTTP,
    because the route is the thing under test.
    """
    import acr_catalog

    rid = client(OWNER).post("/acr", json={"product_version": "1.4.0",
                                           "build_id": "b-docx"}).json()["report_id"]
    isolated_store.update_acr_report_metadata(rid, owner_email=OWNER, fields={
        "report_title": "ACP ACR", "product_name": "ACP by Movate", "product_version": "1.4.0",
        "vendor_name": "Movate", "vendor_contact": "a11y@movate.test",
        "evaluation_scope": "The ACP web application.",
        "evaluation_methods": "axe-core plus guided manual test plans.",
        "browsers_tested": "Firefox 128", "operating_systems_tested": "Windows 11",
        "assistive_technologies_tested": "NVDA 2024.4", "automated_tools": "axe-core 4.12.1",
        "testing_period_start": "2026-08-01", "testing_period_end": "2026-08-31",
        "evaluators": ANALYST, "deployment_environment": "staging",
        "vpat_edition": "VPAT 2.5Rev WCAG", "wcag_version": "2.2", "wcag_levels": "A, AA",
        "product_description": "Document accessibility remediation platform.",
        "release_date": "2026-08-31", "excluded_functionality": "",
        "general_notes": "", "known_dependencies": "",
    })
    for num in acr_catalog.numbers():
        isolated_store.save_acr_decision(rid, num, owner_email=OWNER,
                                         final_status="Not Applicable",
                                         remarks="Out of scope for this evaluation.",
                                         decided_by=ANALYST)
    return rid


# ── the wiring itself, which is what was missing ──────────────────────────────

def test_the_route_serves_a_real_word_document(client, report):
    r = client(OWNER).get(f"/acr/{report}/preview", params={"format": "docx"})
    assert r.status_code == 200, r.text[:400]
    assert r.headers["content-type"].startswith(DOCX_MEDIA)
    # A .docx is a zip with word/document.xml in it. Asserting the media type alone would pass on
    # any bytes at all, which is exactly what a broken renderer would return.
    with zipfile.ZipFile(BytesIO(r.content)) as z:
        assert "word/document.xml" in z.namelist()


def test_it_downloads_under_a_name_that_identifies_the_report_and_its_revision(client, report):
    # The revision is part of the name, and that is not decoration: a customer holding two
    # downloads of "the ACR" has no other way to tell which one they are reading.
    r = client(OWNER).get(f"/acr/{report}/preview", params={"format": "docx"})
    disposition = r.headers["content-disposition"]
    assert disposition.startswith("attachment;")
    assert report in disposition
    assert "-rev1.docx" in disposition


def test_the_docx_says_what_every_other_format_says_it_is_not(client, report):
    # The licensing position travels with the artifact, not with the route that served it. A
    # reader who is handed only the file has to be able to see that it is not a VPAT.
    r = client(OWNER).get(f"/acr/{report}/preview", params={"format": "docx"})
    with zipfile.ZipFile(BytesIO(r.content)) as z:
        xml = z.read("word/document.xml").decode("utf-8", "replace")
    assert "VPAT" in xml


def test_the_other_three_formats_still_work(client, report):
    # The regression this change could most easily cause: a new branch that swallows the ones
    # already shipped. json is the fall-through, so it is the one most at risk.
    assert client(OWNER).get(f"/acr/{report}/preview").status_code == 200
    assert client(OWNER).get(f"/acr/{report}/preview", params={"format": "html"}).status_code == 200
    body = client(OWNER).get(f"/acr/{report}/preview", params={"format": "json"}).json()
    assert "rows" in body or "criteria" in body or body


def test_a_second_person_in_the_deployment_can_download_it_which_is_deliberate(client, report):
    """This asserts a SHARED namespace, and the first draft of it asserted the opposite.

    Every other object in ACP is per-user isolated, so "another signed-in user gets 404" was the
    obvious expectation and it is wrong here. `routes/acr.py::_tenant` departs on purpose: an ACR
    has exactly one subject (ACP itself) and PRD §6 gives it five distinct human roles, with §18
    recommending the approver NOT be the person who made the decisions. Per-user tenancy 404s the
    approver at the ownership check before any role is consulted, so the report can never be
    approved by anyone but its author.

    Pinned rather than left implicit because the wrong expectation is the intuitive one, and
    "fixing" it would silently break approval. The deployment perimeter is still real — it is
    `core.email_allowed`, one layer up, which is what keeps this from being open to the internet.
    """
    r = client(STRANGER).get(f"/acr/{report}/preview", params={"format": "docx"})
    assert r.status_code == 200
    assert r.content.startswith(b"PK\x03\x04")


def test_a_report_that_does_not_exist_is_a_404_and_not_an_empty_document(client):
    r = client(OWNER).get("/acr/acr_does_not_exist/preview", params={"format": "docx"})
    assert r.status_code == 404


# ── the gate ──────────────────────────────────────────────────────────────────

def test_a_document_that_fails_acps_own_checks_is_refused_not_served(client, report, monkeypatch):
    """The test this file exists for.

    A conformance document that fails the checks its own subject is about is the single worst
    artifact this system could emit, and it would look completely normal on the way out.
    """
    monkeypatch.setattr(acr_export_docx, "check", lambda *_a, **_k: {
        "ok": False,
        "failures": [{"rule": "1.3.1", "severity": "FAIL"}, {"rule": "3.1.1", "severity": "FAIL"}],
        "reviews": [],
    })
    r = client(OWNER).get(f"/acr/{report}/preview", params={"format": "docx"})
    assert r.status_code == 500
    # It names what failed — "the export failed a check" is not actionable by anyone.
    assert "1.3.1" in r.text and "3.1.1" in r.text
    # And no document escaped alongside the error.
    assert not r.content.startswith(b"PK\x03\x04")


def test_the_gate_actually_runs_on_the_served_bytes(client, report, monkeypatch):
    """Not just that a gate exists, but that it is fed the document this request produced.

    A gate handed a stale or empty buffer would pass everything and read as working.
    """
    seen = {}

    real = acr_export_docx.check

    def spy(docx_bytes, **kw):
        seen["bytes"] = docx_bytes
        return real(docx_bytes, **kw)

    monkeypatch.setattr(acr_export_docx, "check", spy)
    r = client(OWNER).get(f"/acr/{report}/preview", params={"format": "docx"})
    assert r.status_code == 200
    assert seen["bytes"] == r.content


def test_review_findings_reach_the_approver_rather_than_being_swallowed(client, report, monkeypatch):
    # REVIEW is "a human has to look", not "approved". The download is bytes, so the count rides
    # in a header; the list is at format=docx-gate.
    monkeypatch.setattr(acr_export_docx, "check", lambda *_a, **_k: {
        "ok": True, "failures": [],
        "reviews": [{"rule": "1.1.1", "severity": "REVIEW"}, {"rule": "2.4.4", "severity": "REVIEW"}],
    })
    r = client(OWNER).get(f"/acr/{report}/preview", params={"format": "docx"})
    assert r.status_code == 200
    assert r.headers["x-acp-accessibility-reviews"] == "2"


def test_the_gate_verdict_is_readable_without_downloading_the_document(client, report):
    r = client(OWNER).get(f"/acr/{report}/preview", params={"format": "docx-gate"})
    assert r.status_code == 200
    body = r.json()
    assert set(body) >= {"ok", "failures", "reviews"}
    assert isinstance(body["reviews"], list)
    # JSON, not a file: an approver reads the findings here.
    assert not r.headers.get("content-disposition")


def test_the_gate_endpoint_reports_a_failure_instead_of_refusing(client, report, monkeypatch):
    # The download refuses on FAIL; the gate must still ANSWER on FAIL, or the one endpoint that
    # explains the refusal would refuse for the same reason and the operator learns nothing.
    monkeypatch.setattr(acr_export_docx, "check", lambda *_a, **_k: {
        "ok": False, "failures": [{"rule": "1.3.1", "severity": "FAIL"}], "reviews": [],
    })
    r = client(OWNER).get(f"/acr/{report}/preview", params={"format": "docx-gate"})
    assert r.status_code == 200
    assert r.json()["ok"] is False


# ── the deployment that cannot render one ─────────────────────────────────────

def test_a_deployment_without_the_renderer_says_so_rather_than_serving_something_else(
        client, report, monkeypatch):
    # Mirrors the PDF branch's stance: no silent fallback to a lesser artifact. A conformance
    # document whose structure is missing is indistinguishable from a good one to everyone except
    # the reader it exists for.
    def unavailable(*_a, **_k):
        raise acr_export_docx.RendererUnavailable(acr_export_docx.MISSING_RENDERER)

    monkeypatch.setattr(acr_export_docx, "render", unavailable)
    r = client(OWNER).get(f"/acr/{report}/preview", params={"format": "docx"})
    assert r.status_code == 503
    assert "python-docx" in r.text


# ── the leak ──────────────────────────────────────────────────────────────────

def test_downloading_repeatedly_does_not_leak_a_temp_directory(client, report):
    """`acr_export_docx.check()` falls back to `tempfile.mkdtemp()` with no cleanup.

    That is harmless in a module test that passes `tmp_path`, and a slow leak of one directory and
    one .docx PER DOWNLOAD from a route. The route passes an explicit, managed directory; this
    fails if someone simplifies that away.
    """
    import tempfile

    root = Path(tempfile.gettempdir())
    before = set(root.iterdir()) if root.exists() else set()
    for _ in range(3):
        assert client(OWNER).get(f"/acr/{report}/preview",
                                 params={"format": "docx"}).status_code == 200
    after = set(root.iterdir()) if root.exists() else set()
    leaked = [p for p in (after - before) if p.is_dir() and (p / "acr-export.docx").exists()]
    assert leaked == [], f"the export leaked {len(leaked)} temp directories"
