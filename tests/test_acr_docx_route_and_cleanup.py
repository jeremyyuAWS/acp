"""Finishing the Word export: the temp-directory leak, and the published revision.

THREE CLAIMS, each of which was a real gap rather than a hypothetical:

1. `acr_export_docx.check()` used to fall back to `tempfile.mkdtemp()` with no cleanup, so every
   caller that did not pass `tmp_dir` leaked one directory and one .docx **per call** — and the
   export route calls it on every download. #1499 contained it by wrapping the call site in a
   `TemporaryDirectory`, which is the tell that the obligation was in the wrong place.

2. The published-revision export served `pdf` and `html` only. A report could therefore be sent
   to a customer as a published PDF but only ever as a **draft** Word document — an asymmetry
   nobody notices until the two documents disagree, which is exactly when it matters.

3. The 500 raised when the Word export fails its own accessibility gate read the finding keys
   `rule` and `criterion`. `office_structure._finding` writes **`ruleId`**. So the message that
   exists to name the failing check could only ever say "unnamed checks".
"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

pytest.importorskip("docx")

import acr_export_docx  # noqa: E402
import acr_export_preview  # noqa: E402

OWNER = "owner@acp.test"
APPROVER = "approver@acp.test"
ANALYST = "analyst@acp.test"

REPORT = {"report_title": "ACP ACR", "wcag_version": "2.2"}
CRITERIA = [{"criterion_num": "1.4.3", "criterion_name": "Contrast (Minimum)", "level": "AA",
             "principle": "Perceivable", "final_status": "Supports", "remarks": "ok"}]


# ── 1. the leak ────────────────────────────────────────────────────────────────

def test_check_cleans_up_the_directory_it_creates(monkeypatch, tmp_path):
    """The defect: one directory and one .docx left behind per call, on the path the export route
    takes on every download.

    Asserted by pointing tempfile at an empty directory and counting what survives, rather than by
    reading the source — the previous version passed every test it had while leaking.
    """
    import tempfile

    scratch = tmp_path / "tmproot"
    scratch.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))

    document = acr_export_docx.render(acr_export_preview.project(REPORT, CRITERIA))
    for _ in range(3):
        acr_export_docx.check(document)

    leftovers = list(scratch.iterdir())
    assert leftovers == [], f"check() left {len(leftovers)} entries behind: {leftovers[:3]}"


def test_check_still_honours_an_explicit_directory(tmp_path):
    """`tmp_dir` stays, for tests that want to inspect what was written. A caller that owns the
    directory owns its lifetime, so this one is NOT cleaned up — that is the contract."""
    document = acr_export_docx.render(acr_export_preview.project(REPORT, CRITERIA))
    target = tmp_path / "mine"
    result = acr_export_docx.check(document, tmp_dir=target)
    assert result["ok"] is True
    assert (target / "acr-export.docx").exists(), "the caller's directory was not used"


# ── 2. the published revision ──────────────────────────────────────────────────

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


@pytest.fixture()
def published(client, isolated_store):
    import acr_catalog

    rid = client(OWNER).post("/acr", json={"product_version": "1.4.0",
                                           "build_id": "b-900"}).json()["report_id"]
    client(OWNER).put(f"/acr/{rid}/roles", json={"email": ANALYST, "role": "editor"})
    client(OWNER).put(f"/acr/{rid}/roles", json={"email": APPROVER, "role": "approver"})
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
        isolated_store.approve_acr_criterion(rid, num, owner_email=OWNER, reviewer=APPROVER)
    assert client(APPROVER).post(f"/acr/{rid}/publish").status_code == 200
    return rid


def _doc_xml(blob: bytes, tmp_path) -> str:
    path = tmp_path / "r.docx"
    path.write_bytes(blob)
    with zipfile.ZipFile(path) as zf:
        return zf.read("word/document.xml").decode("utf-8")


def test_a_published_revision_downloads_as_a_word_document(client, published, tmp_path):
    r = client(ANALYST).get(f"/acr/{published}/revisions/1/export", params={"format": "docx"})
    assert r.status_code == 200, r.text[:400]
    assert r.content[:2] == b"PK"
    assert "wordprocessingml" in r.headers["content-type"]
    disp = r.headers.get("content-disposition", "")
    assert "-rev1.docx" in disp, disp


def test_the_published_word_document_states_its_revision_and_digest(client, published, tmp_path):
    """Same claim the published PDF makes, in the format a customer is most likely to open. A
    reader holding both must not find them saying different things about one revision."""
    digest = client(ANALYST).get(f"/acr/{published}/revisions/1").json()["content_digest"]
    blob = client(ANALYST).get(f"/acr/{published}/revisions/1/export",
                               params={"format": "docx"}).content
    doc = _doc_xml(blob, tmp_path)

    assert "Published revision 1" in doc
    assert digest in doc, "the full digest is not in the document"
    assert "not a digital signature" in doc
    assert "immutable published record" in doc


def test_the_published_word_document_still_says_it_is_not_a_vpat(client, published, tmp_path):
    blob = client(ANALYST).get(f"/acr/{published}/revisions/1/export",
                               params={"format": "docx"}).content
    doc = _doc_xml(blob, tmp_path)
    assert "not a VPAT" in doc
    assert "veraPDF" not in doc, "the PDF renderer's validation was claimed about a Word file"


def test_a_tampered_snapshot_is_never_rendered_as_word_either(client, published, isolated_store):
    """The digest gate runs before the format branch, so it must hold for every format. Asserting
    it per-format is what stops a later branch being added above the gate."""
    with isolated_store._db.cursor() as cur:
        isolated_store._db.execute(
            cur, "UPDATE acr_snapshot SET content_json=%s WHERE report_id=%s",
            ('{"schema":"acp.acr.snapshot/1","criteria":[],"totals":{"total":0}}', published))

    r = client(ANALYST).get(f"/acr/{published}/revisions/1/export", params={"format": "docx"})
    assert r.status_code == 409
    assert r.content[:2] != b"PK"
    assert "altered since publication" in r.json()["detail"]


def test_the_published_export_exposes_its_gate(client, published):
    """`format=docx-gate` returns the analyser result rather than the file, so the detail behind a
    refusal is inspectable without downloading anything."""
    gate = client(ANALYST).get(f"/acr/{published}/revisions/1/export",
                               params={"format": "docx-gate"}).json()
    assert set(gate) == {"ok", "failures", "reviews"}
    assert gate["ok"] is True


def test_the_published_word_export_refuses_when_it_fails_its_own_gate(
        client, published, monkeypatch):
    """The gate is load-bearing, not decorative. ACP failing its own document checks on a document
    ACP just generated is a renderer defect, and serving it anyway would ship an inaccessible
    accessibility report — the one artifact that cannot be allowed through."""
    monkeypatch.setattr(acr_export_docx, "check", lambda *a, **k: {
        "ok": False, "failures": [{"ruleId": "DOCX_HEADING_SKIP"}], "reviews": []})
    r = client(ANALYST).get(f"/acr/{published}/revisions/1/export", params={"format": "docx"})
    assert r.status_code == 500
    assert r.content[:2] != b"PK"
    # 3. the key that could only ever say "unnamed checks"
    assert "DOCX_HEADING_SKIP" in r.json()["detail"], r.json()["detail"]


def test_the_draft_export_names_its_failing_checks_too(client, published, monkeypatch):
    """Same message, same wrong-key defect, on the route #1499 added."""
    monkeypatch.setattr(acr_export_docx, "check", lambda *a, **k: {
        "ok": False, "failures": [{"ruleId": "DOCX_EMPTY_HEADING"}], "reviews": []})
    r = client(ANALYST).get(f"/acr/{published}/preview", params={"format": "docx"})
    assert r.status_code == 500
    assert "DOCX_EMPTY_HEADING" in r.json()["detail"], r.json()["detail"]


def test_the_review_count_travels_with_the_published_file(client, published):
    """REVIEW is "a human has to look", not "approved". The count rides on the response so a
    download cannot silently imply that nothing needs signing off."""
    r = client(ANALYST).get(f"/acr/{published}/revisions/1/export", params={"format": "docx"})
    assert "X-ACP-Accessibility-Reviews" in r.headers
    assert r.headers["X-ACP-Accessibility-Reviews"].isdigit()
