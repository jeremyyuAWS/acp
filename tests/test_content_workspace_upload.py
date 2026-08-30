"""ACP Managed Content Workspace (ADR 0044, PRD §9) — the upload-session and
completion endpoints.

Hermetic: workspace_blob's public functions are monkeypatched directly (no need for the
sys.modules azure-faking dance test_workspace_blob.py uses — that module's own tests already
cover its real internals; these tests are about the ROUTE's logic: validation, ownership,
server-side size verification, and document/version bookkeeping).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

OWNER = "alice@x.com"
OTHER = "bob@y.com"

_FAKE_AUTH = {"version_id": "v-001", "blob_path": "workspace/alice@x.com/ws1/doc1/source/v-001/original",
              "upload_url": "https://fake.blob.core.windows.net/workspace-content/...", "expires_at": "2026-08-30T00:00:00+00:00"}


@pytest.fixture()
def gated_client(monkeypatch, isolated_store):
    """Mirrors tests/test_content_workspaces.py's fixture exactly."""
    import core
    from fastapi.testclient import TestClient
    from app import app

    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setattr(core, "ACCESS_CODE", "", raising=False)
    monkeypatch.setattr(core, "GOOGLE_CLIENT_ID", "test-client-id", raising=False)
    monkeypatch.setattr(core, "E2E_KEY", None, raising=False)
    monkeypatch.setattr(core, "OWNER_EMAIL", OWNER, raising=False)
    monkeypatch.setattr(core, "verify_gis_token", lambda tok: tok or None)
    monkeypatch.setattr(core, "email_allowed", lambda e: e in (OWNER, OTHER))

    client = TestClient(app)

    def as_user(email):
        client.headers.update({"Authorization": f"Bearer {email}"})
        return client

    return as_user


@pytest.fixture(autouse=True)
def _blob_enabled(monkeypatch):
    """Default: workspace_blob acts configured, generate_upload_authorization succeeds. Tests
    that want the unconfigured/failure paths override these explicitly."""
    import workspace_blob
    monkeypatch.setattr(workspace_blob, "enabled", lambda: True)
    monkeypatch.setattr(workspace_blob, "generate_upload_authorization",
                        lambda owner, ws, doc, **kw: dict(_FAKE_AUTH))


def _make_workspace(gated_client, owner=OWNER):
    return gated_client(owner).post("/content-workspaces", json={"name": "Uploads"}).json()["id"]


# ── create_upload_session ────────────────────────────────────────────────────

def test_happy_path_returns_document_id_and_authorization(gated_client):
    ws = _make_workspace(gated_client)
    r = gated_client(OWNER).post(f"/content-workspaces/{ws}/documents/upload-session",
                                 json={"filename": "report.pdf", "size_bytes": 1024})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["document_id"]
    assert body["version_id"] == "v-001"
    assert body["upload_url"] == _FAKE_AUTH["upload_url"]


def test_session_creates_a_document_row_in_uploading_state(gated_client, isolated_store):
    ws = _make_workspace(gated_client)
    r = gated_client(OWNER).post(f"/content-workspaces/{ws}/documents/upload-session",
                                 json={"filename": "report.pdf", "size_bytes": 1024,
                                       "relative_path": "Legal/report.pdf"})
    doc_id = r.json()["document_id"]
    doc = isolated_store.get_content_workspace_document(doc_id, owner_email=OWNER)
    assert doc["status"] == "uploading"
    assert doc["display_name"] == "report.pdf"
    assert doc["relative_path"] == "Legal/report.pdf"


def test_404_for_a_foreign_workspace(gated_client):
    ws = _make_workspace(gated_client, owner=OWNER)
    r = gated_client(OTHER).post(f"/content-workspaces/{ws}/documents/upload-session",
                                 json={"filename": "x.pdf", "size_bytes": 1})
    assert r.status_code == 404


def test_404_for_a_nonexistent_workspace(gated_client):
    r = gated_client(OWNER).post("/content-workspaces/does-not-exist/documents/upload-session",
                                 json={"filename": "x.pdf", "size_bytes": 1})
    assert r.status_code == 404


def test_empty_filename_is_rejected(gated_client):
    ws = _make_workspace(gated_client)
    r = gated_client(OWNER).post(f"/content-workspaces/{ws}/documents/upload-session",
                                 json={"filename": "   ", "size_bytes": 1})
    assert r.status_code == 422


def test_non_positive_size_is_rejected(gated_client):
    ws = _make_workspace(gated_client)
    r = gated_client(OWNER).post(f"/content-workspaces/{ws}/documents/upload-session",
                                 json={"filename": "x.pdf", "size_bytes": 0})
    assert r.status_code == 422


def test_oversized_upload_is_rejected(gated_client, monkeypatch):
    import routes.content_workspaces as cw
    monkeypatch.setattr(cw, "_MAX_UPLOAD_BYTES", 100)
    ws = _make_workspace(gated_client)
    r = gated_client(OWNER).post(f"/content-workspaces/{ws}/documents/upload-session",
                                 json={"filename": "huge.pdf", "size_bytes": 101})
    assert r.status_code == 413


def test_upload_session_rejected_when_it_would_exceed_the_workspace_quota(gated_client, monkeypatch):
    import routes.content_workspaces as cw
    monkeypatch.setattr(cw, "_WORKSPACE_QUOTA_BYTES", 1000)
    ws = _make_workspace(gated_client)
    r = gated_client(OWNER).post(f"/content-workspaces/{ws}/documents/upload-session",
                                 json={"filename": "huge.pdf", "size_bytes": 1001})
    assert r.status_code == 413


def test_upload_session_allowed_exactly_at_the_quota(gated_client, monkeypatch):
    import routes.content_workspaces as cw
    monkeypatch.setattr(cw, "_WORKSPACE_QUOTA_BYTES", 1000)
    ws = _make_workspace(gated_client)
    r = gated_client(OWNER).post(f"/content-workspaces/{ws}/documents/upload-session",
                                 json={"filename": "report.pdf", "size_bytes": 1000})
    assert r.status_code == 200, r.text


def test_upload_session_quota_accounts_for_bytes_already_stored(gated_client, monkeypatch):
    """The quota is checked against USAGE + this upload, not this upload alone — a workspace
    that already holds 900 bytes has only 100 left of a 1000-byte quota."""
    import routes.content_workspaces as cw
    monkeypatch.setattr(cw, "_WORKSPACE_QUOTA_BYTES", 1000)
    ws = _make_workspace(gated_client)
    doc_id, version_id = _start_upload(gated_client, ws, filename="a.pdf", size_bytes=900)
    _mock_uploaded(monkeypatch, size=900, prefix=b"%PDF-1.7")
    r1 = _complete(gated_client, ws, doc_id, version_id, content_hash="h1", size_bytes=900)
    assert r1.json()["status"] == "ready"

    r2 = gated_client(OWNER).post(f"/content-workspaces/{ws}/documents/upload-session",
                                  json={"filename": "b.pdf", "size_bytes": 101})
    assert r2.status_code == 413

    r3 = gated_client(OWNER).post(f"/content-workspaces/{ws}/documents/upload-session",
                                  json={"filename": "b.pdf", "size_bytes": 100})
    assert r3.status_code == 200, r3.text


def test_upload_session_quota_is_scoped_to_the_workspace(gated_client, monkeypatch):
    import routes.content_workspaces as cw
    monkeypatch.setattr(cw, "_WORKSPACE_QUOTA_BYTES", 1000)
    ws1 = _make_workspace(gated_client)
    ws2 = _make_workspace(gated_client)
    doc_id, version_id = _start_upload(gated_client, ws1, filename="a.pdf", size_bytes=900)
    _mock_uploaded(monkeypatch, size=900, prefix=b"%PDF-1.7")
    _complete(gated_client, ws1, doc_id, version_id, content_hash="h1", size_bytes=900)

    r = gated_client(OWNER).post(f"/content-workspaces/{ws2}/documents/upload-session",
                                 json={"filename": "b.pdf", "size_bytes": 900})
    assert r.status_code == 200, r.text


def test_503_when_workspace_blob_is_not_configured(gated_client, monkeypatch):
    import workspace_blob
    monkeypatch.setattr(workspace_blob, "enabled", lambda: False)
    ws = _make_workspace(gated_client)
    r = gated_client(OWNER).post(f"/content-workspaces/{ws}/documents/upload-session",
                                 json={"filename": "x.pdf", "size_bytes": 1})
    assert r.status_code == 503


def test_document_marked_failed_when_authorization_issuance_fails(gated_client, monkeypatch, isolated_store):
    import workspace_blob
    monkeypatch.setattr(workspace_blob, "generate_upload_authorization", lambda *a, **kw: None)
    ws = _make_workspace(gated_client)
    r = gated_client(OWNER).post(f"/content-workspaces/{ws}/documents/upload-session",
                                 json={"filename": "x.pdf", "size_bytes": 1})
    assert r.status_code == 503
    docs = isolated_store.list_content_workspace_documents(ws, owner_email=OWNER)
    assert docs[0]["status"] == "failed"


def test_session_creation_is_logged(gated_client, isolated_store):
    ws = _make_workspace(gated_client)
    gated_client(OWNER).post(f"/content-workspaces/{ws}/documents/upload-session",
                             json={"filename": "x.pdf", "size_bytes": 1})
    decisions = isolated_store.list_decisions()
    assert any(d["action"] == "content_workspace.upload_session_created" for d in decisions)


# ── complete_upload ───────────────────────────────────────────────────────────

def _start_upload(gated_client, ws, *, filename="report.pdf", size_bytes=1024):
    r = gated_client(OWNER).post(f"/content-workspaces/{ws}/documents/upload-session",
                                 json={"filename": filename, "size_bytes": size_bytes})
    return r.json()["document_id"], r.json()["version_id"]


def _mock_uploaded(monkeypatch, *, size=1024, prefix=b"%PDF-1.7"):
    """Defaults to a valid PDF signature so existing tests exercise the happy (non-quarantine)
    path without each needing to know about magic-byte verification; tests that care about
    quarantine behavior override `prefix` explicitly."""
    import workspace_blob
    monkeypatch.setattr(workspace_blob, "get_uploaded_blob_properties",
                        lambda *a, **kw: {"size": size, "content_md5": None})
    monkeypatch.setattr(workspace_blob, "download_document_prefix", lambda *a, **kw: prefix)


def test_complete_happy_path(gated_client, monkeypatch):
    ws = _make_workspace(gated_client)
    doc_id, version_id = _start_upload(gated_client, ws)
    _mock_uploaded(monkeypatch, size=1024)

    r = gated_client(OWNER).post(f"/content-workspaces/{ws}/documents/{doc_id}/complete",
                                 json={"version_id": version_id, "content_hash": "h1",
                                       "size_bytes": 1024, "mime_type": "application/pdf"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ready"
    assert len(body["versions"]) == 1
    assert body["versions"][0]["content_hash"] == "h1"
    assert body["versions"][0]["version_seq"] == 1


def test_complete_updates_document_status_to_ready(gated_client, monkeypatch, isolated_store):
    ws = _make_workspace(gated_client)
    doc_id, version_id = _start_upload(gated_client, ws)
    _mock_uploaded(monkeypatch, size=1024)
    gated_client(OWNER).post(f"/content-workspaces/{ws}/documents/{doc_id}/complete",
                             json={"version_id": version_id, "content_hash": "h1", "size_bytes": 1024})
    assert isolated_store.get_content_workspace_document(doc_id, owner_email=OWNER)["status"] == "ready"


def test_complete_404_for_a_foreign_workspace(gated_client, monkeypatch):
    ws = _make_workspace(gated_client, owner=OWNER)
    doc_id, version_id = _start_upload(gated_client, ws)
    _mock_uploaded(monkeypatch)
    r = gated_client(OTHER).post(f"/content-workspaces/{ws}/documents/{doc_id}/complete",
                                 json={"version_id": version_id, "content_hash": "h1", "size_bytes": 1024})
    assert r.status_code == 404


def test_complete_404_for_a_nonexistent_document(gated_client, monkeypatch):
    ws = _make_workspace(gated_client)
    _mock_uploaded(monkeypatch)
    r = gated_client(OWNER).post(f"/content-workspaces/{ws}/documents/does-not-exist/complete",
                                 json={"version_id": "v1", "content_hash": "h1", "size_bytes": 1024})
    assert r.status_code == 404


def test_complete_409_when_the_blob_was_never_uploaded(gated_client, monkeypatch):
    import workspace_blob
    ws = _make_workspace(gated_client)
    doc_id, version_id = _start_upload(gated_client, ws)
    monkeypatch.setattr(workspace_blob, "get_uploaded_blob_properties", lambda *a, **kw: None)

    r = gated_client(OWNER).post(f"/content-workspaces/{ws}/documents/{doc_id}/complete",
                                 json={"version_id": version_id, "content_hash": "h1", "size_bytes": 1024})
    assert r.status_code == 409


def test_complete_422_on_a_size_mismatch(gated_client, monkeypatch):
    ws = _make_workspace(gated_client)
    doc_id, version_id = _start_upload(gated_client, ws)
    _mock_uploaded(monkeypatch, size=999)  # actual blob size differs from the client's claim

    r = gated_client(OWNER).post(f"/content-workspaces/{ws}/documents/{doc_id}/complete",
                                 json={"version_id": version_id, "content_hash": "h1", "size_bytes": 1024})
    assert r.status_code == 422


def test_complete_never_trusts_a_client_supplied_blob_path(gated_client, monkeypatch):
    """The request model has no blob_path field at all — the server always recomputes it via
    workspace_blob.blob_path from (owner, workspace_id, document_id, version_id), so there is
    no way for a client to point a version at someone else's blob."""
    import workspace_blob
    ws = _make_workspace(gated_client)
    doc_id, version_id = _start_upload(gated_client, ws)
    _mock_uploaded(monkeypatch, size=1024)

    r = gated_client(OWNER).post(f"/content-workspaces/{ws}/documents/{doc_id}/complete",
                                 json={"version_id": version_id, "content_hash": "h1",
                                       "size_bytes": 1024, "blob_path": "workspace/someone-else/x/y/source/z/original"})
    assert r.status_code == 200
    expected = workspace_blob.blob_path(OWNER, ws, doc_id, version_id)
    assert r.json()["versions"][0]["blob_path"] == expected


def test_completing_a_second_upload_against_the_same_document_is_version_2(gated_client, monkeypatch):
    """create_upload_session always mints a brand-new document (item 21 will add proper
    reuse/new-version UX) — but complete_upload itself has no opinion on whether a document
    already has a version, so two completions against the SAME document_id (as item 21's
    'upload as a new version' flow will eventually drive) already produce seq 1 then 2."""
    ws = _make_workspace(gated_client)
    doc_id, v1 = _start_upload(gated_client, ws)
    _mock_uploaded(monkeypatch, size=1024)
    gated_client(OWNER).post(f"/content-workspaces/{ws}/documents/{doc_id}/complete",
                             json={"version_id": v1, "content_hash": "h1", "size_bytes": 1024})

    gated_client(OWNER).post(f"/content-workspaces/{ws}/documents/{doc_id}/complete",
                             json={"version_id": "v-002", "content_hash": "h2", "size_bytes": 1024})

    doc = gated_client(OWNER).get(f"/content-workspaces/{ws}/documents/{doc_id}").json()
    seqs = sorted(v["version_seq"] for v in doc["versions"])
    assert seqs == [1, 2]


# ── list / get documents ──────────────────────────────────────────────────────

def test_list_documents_in_a_workspace(gated_client, monkeypatch):
    ws = _make_workspace(gated_client)
    doc_id, version_id = _start_upload(gated_client, ws, filename="a.pdf")
    _mock_uploaded(monkeypatch)
    gated_client(OWNER).post(f"/content-workspaces/{ws}/documents/{doc_id}/complete",
                             json={"version_id": version_id, "content_hash": "h1", "size_bytes": 1024})

    r = gated_client(OWNER).get(f"/content-workspaces/{ws}/documents")
    assert r.status_code == 200
    names = [d["display_name"] for d in r.json()["documents"]]
    assert names == ["a.pdf"]


def test_list_documents_404s_for_a_foreign_workspace(gated_client):
    ws = _make_workspace(gated_client, owner=OWNER)
    r = gated_client(OTHER).get(f"/content-workspaces/{ws}/documents")
    assert r.status_code == 404


def test_get_document_includes_its_versions(gated_client, monkeypatch):
    ws = _make_workspace(gated_client)
    doc_id, version_id = _start_upload(gated_client, ws)
    _mock_uploaded(monkeypatch)
    gated_client(OWNER).post(f"/content-workspaces/{ws}/documents/{doc_id}/complete",
                             json={"version_id": version_id, "content_hash": "h1", "size_bytes": 1024})

    r = gated_client(OWNER).get(f"/content-workspaces/{ws}/documents/{doc_id}")
    assert r.status_code == 200
    assert len(r.json()["versions"]) == 1


def test_get_document_404s_for_a_foreign_owner(gated_client, monkeypatch):
    ws = _make_workspace(gated_client, owner=OWNER)
    doc_id, version_id = _start_upload(gated_client, ws)
    r = gated_client(OTHER).get(f"/content-workspaces/{ws}/documents/{doc_id}")
    assert r.status_code == 404


# ── extension allow-list (PRD §13) ───────────────────────────────────────────

def test_upload_session_rejects_an_unsupported_extension(gated_client):
    ws = _make_workspace(gated_client)
    r = gated_client(OWNER).post(f"/content-workspaces/{ws}/documents/upload-session",
                                 json={"filename": "malware.exe", "size_bytes": 1024})
    assert r.status_code == 422


def test_upload_session_rejects_a_filename_with_no_extension(gated_client):
    ws = _make_workspace(gated_client)
    r = gated_client(OWNER).post(f"/content-workspaces/{ws}/documents/upload-session",
                                 json={"filename": "noextension", "size_bytes": 1024})
    assert r.status_code == 422


@pytest.mark.parametrize("filename", ["report.pdf", "brief.docx", "deck.pptx", "sheet.xlsx",
                                      "page.html", "page.htm", "Report.PDF"])
def test_upload_session_accepts_every_prd_supported_extension(gated_client, filename):
    ws = _make_workspace(gated_client)
    r = gated_client(OWNER).post(f"/content-workspaces/{ws}/documents/upload-session",
                                 json={"filename": filename, "size_bytes": 1024})
    assert r.status_code == 200, r.text


# ── magic-byte / quarantine flow (PRD §13, §8) ───────────────────────────────

def test_complete_quarantines_a_pdf_with_the_wrong_signature(gated_client, monkeypatch):
    ws = _make_workspace(gated_client)
    doc_id, version_id = _start_upload(gated_client, ws, filename="report.pdf")
    _mock_uploaded(monkeypatch, size=1024, prefix=b"not a pdf")

    r = gated_client(OWNER).post(f"/content-workspaces/{ws}/documents/{doc_id}/complete",
                                 json={"version_id": version_id, "content_hash": "h1", "size_bytes": 1024})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "quarantined"
    assert body["versions"][0]["lifecycle_state"] == "quarantined"


def test_complete_quarantines_when_the_prefix_read_fails(gated_client, monkeypatch):
    """download_document_prefix returning None (blob missing, ranged read failed, ...) is
    treated the same as an outright mismatch — 'can't verify' is not 'verified clean'."""
    ws = _make_workspace(gated_client)
    doc_id, version_id = _start_upload(gated_client, ws, filename="report.pdf")
    _mock_uploaded(monkeypatch, size=1024, prefix=None)

    r = gated_client(OWNER).post(f"/content-workspaces/{ws}/documents/{doc_id}/complete",
                                 json={"version_id": version_id, "content_hash": "h1", "size_bytes": 1024})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "quarantined"


def test_complete_accepts_a_matching_pdf_signature(gated_client, monkeypatch):
    ws = _make_workspace(gated_client)
    doc_id, version_id = _start_upload(gated_client, ws, filename="report.pdf")
    _mock_uploaded(monkeypatch, size=1024, prefix=b"%PDF-1.7")

    r = gated_client(OWNER).post(f"/content-workspaces/{ws}/documents/{doc_id}/complete",
                                 json={"version_id": version_id, "content_hash": "h1", "size_bytes": 1024})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ready"


def test_complete_accepts_a_matching_office_zip_signature(gated_client, monkeypatch):
    ws = _make_workspace(gated_client)
    doc_id, version_id = _start_upload(gated_client, ws, filename="brief.docx")
    _mock_uploaded(monkeypatch, size=1024, prefix=b"PK\x03\x04\x14\x00\x06\x00")

    r = gated_client(OWNER).post(f"/content-workspaces/{ws}/documents/{doc_id}/complete",
                                 json={"version_id": version_id, "content_hash": "h1", "size_bytes": 1024})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ready"


def test_complete_does_not_signature_check_html(gated_client, monkeypatch):
    """HTML has no reliable leading signature — allow-listed at session creation, but not
    enforced at completion time (see _SIGNATURES' docstring)."""
    ws = _make_workspace(gated_client)
    doc_id, version_id = _start_upload(gated_client, ws, filename="page.html")
    _mock_uploaded(monkeypatch, size=1024, prefix=b"<!doctype html>")

    r = gated_client(OWNER).post(f"/content-workspaces/{ws}/documents/{doc_id}/complete",
                                 json={"version_id": version_id, "content_hash": "h1", "size_bytes": 1024})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ready"


def test_quarantined_version_still_gets_a_row_and_is_not_dropped(gated_client, monkeypatch, isolated_store):
    """A signature mismatch is a normal terminal state (PRD §8), not a dropped upload — the
    version row is still created so the bytes and their fate are recorded."""
    ws = _make_workspace(gated_client)
    doc_id, version_id = _start_upload(gated_client, ws, filename="report.pdf")
    _mock_uploaded(monkeypatch, size=1024, prefix=b"not a pdf")
    gated_client(OWNER).post(f"/content-workspaces/{ws}/documents/{doc_id}/complete",
                             json={"version_id": version_id, "content_hash": "h1", "size_bytes": 1024})

    versions = isolated_store.list_content_workspace_document_versions(doc_id)
    assert len(versions) == 1
    assert versions[0]["lifecycle_state"] == "quarantined"


def test_every_new_version_is_stamped_not_scanned(gated_client, monkeypatch, isolated_store):
    """No real malware scanner is wired up (yet) — the field says so honestly rather than
    fabricating a 'clean' result."""
    ws = _make_workspace(gated_client)
    doc_id, version_id = _start_upload(gated_client, ws)
    _mock_uploaded(monkeypatch)
    gated_client(OWNER).post(f"/content-workspaces/{ws}/documents/{doc_id}/complete",
                             json={"version_id": version_id, "content_hash": "h1", "size_bytes": 1024})

    versions = isolated_store.list_content_workspace_document_versions(doc_id)
    assert versions[0]["malware_status"] == "not_scanned"


def test_quarantine_is_logged_distinctly_from_a_normal_completion(gated_client, monkeypatch, isolated_store):
    ws = _make_workspace(gated_client)
    doc_id, version_id = _start_upload(gated_client, ws, filename="report.pdf")
    _mock_uploaded(monkeypatch, size=1024, prefix=b"not a pdf")
    gated_client(OWNER).post(f"/content-workspaces/{ws}/documents/{doc_id}/complete",
                             json={"version_id": version_id, "content_hash": "h1", "size_bytes": 1024})

    decisions = isolated_store.list_decisions()
    assert any(d["action"] == "content_workspace.upload_quarantined" for d in decisions)


# ── duplicate detection (PRD §12) ────────────────────────────────────────────

def _complete(gated_client, ws, doc_id, version_id, *, content_hash="h1", size_bytes=1024):
    return gated_client(OWNER).post(f"/content-workspaces/{ws}/documents/{doc_id}/complete",
                                    json={"version_id": version_id, "content_hash": content_hash,
                                          "size_bytes": size_bytes})


def test_complete_flags_a_duplicate_against_a_different_document(gated_client, monkeypatch):
    ws = _make_workspace(gated_client)
    doc1, v1 = _start_upload(gated_client, ws, filename="a.pdf")
    _mock_uploaded(monkeypatch, size=1024, prefix=b"%PDF-1.7")
    r1 = _complete(gated_client, ws, doc1, v1, content_hash="same-hash")
    assert r1.json()["status"] == "ready"

    doc2, _ = _start_upload(gated_client, ws, filename="b.pdf")
    r2 = _complete(gated_client, ws, doc2, "v-002", content_hash="same-hash")
    assert r2.status_code == 200, r2.text
    body = r2.json()
    assert body["status"] == "duplicate"
    assert body["versions"][0]["lifecycle_state"] == "duplicate"
    assert body["duplicate_of"] == {"document_id": doc1, "version_id": v1}


def test_reuploading_the_same_document_with_the_same_hash_is_not_a_duplicate(gated_client, monkeypatch):
    """A match against THIS SAME document (item 19's 'second completion is version 2' case) is
    an ordinary re-upload, not PRD §12 duplicate handling — that UX is about content
    reappearing under a DIFFERENT document."""
    ws = _make_workspace(gated_client)
    doc_id, v1 = _start_upload(gated_client, ws, filename="a.pdf")
    _mock_uploaded(monkeypatch, size=1024, prefix=b"%PDF-1.7")
    _complete(gated_client, ws, doc_id, v1, content_hash="same-hash")

    r2 = _complete(gated_client, ws, doc_id, "v-002", content_hash="same-hash")
    assert r2.json()["status"] == "ready"
    assert "duplicate_of" not in r2.json()


def test_quarantine_takes_precedence_over_duplicate_detection(gated_client, monkeypatch):
    ws = _make_workspace(gated_client)
    doc1, v1 = _start_upload(gated_client, ws, filename="a.pdf")
    _mock_uploaded(monkeypatch, size=1024, prefix=b"%PDF-1.7")
    _complete(gated_client, ws, doc1, v1, content_hash="same-hash")

    doc2, _ = _start_upload(gated_client, ws, filename="b.pdf")
    _mock_uploaded(monkeypatch, size=1024, prefix=b"not a pdf")  # bad signature
    r2 = _complete(gated_client, ws, doc2, "v-002", content_hash="same-hash")
    body = r2.json()
    assert body["status"] == "quarantined"
    assert "duplicate_of" not in body


def test_duplicate_is_logged_distinctly(gated_client, monkeypatch, isolated_store):
    ws = _make_workspace(gated_client)
    doc1, v1 = _start_upload(gated_client, ws, filename="a.pdf")
    _mock_uploaded(monkeypatch, size=1024, prefix=b"%PDF-1.7")
    _complete(gated_client, ws, doc1, v1, content_hash="same-hash")

    doc2, _ = _start_upload(gated_client, ws, filename="b.pdf")
    _complete(gated_client, ws, doc2, "v-002", content_hash="same-hash")

    decisions = isolated_store.list_decisions()
    assert any(d["action"] == "content_workspace.upload_duplicate" for d in decisions)


def test_duplicate_detection_is_scoped_to_the_workspace(gated_client, monkeypatch):
    """The same content in a DIFFERENT workspace is not a duplicate — PRD §12 scopes detection
    to 'anywhere in this workspace', not across the whole account."""
    ws1 = _make_workspace(gated_client)
    ws2 = _make_workspace(gated_client)
    doc1, v1 = _start_upload(gated_client, ws1, filename="a.pdf")
    _mock_uploaded(monkeypatch, size=1024, prefix=b"%PDF-1.7")
    _complete(gated_client, ws1, doc1, v1, content_hash="same-hash")

    doc2, _ = _start_upload(gated_client, ws2, filename="b.pdf")
    r2 = _complete(gated_client, ws2, doc2, "v-002", content_hash="same-hash")
    assert r2.json()["status"] == "ready"


# ── resolve-duplicate (PRD §12) ───────────────────────────────────────────────

def _make_duplicate(gated_client, monkeypatch, ws):
    doc1, v1 = _start_upload(gated_client, ws, filename="a.pdf")
    _mock_uploaded(monkeypatch, size=1024, prefix=b"%PDF-1.7")
    _complete(gated_client, ws, doc1, v1, content_hash="same-hash")
    doc2, _ = _start_upload(gated_client, ws, filename="b.pdf")
    _complete(gated_client, ws, doc2, "v-002", content_hash="same-hash")
    return doc2, "v-002"


def test_resolve_duplicate_rejects_an_unknown_action(gated_client, monkeypatch):
    ws = _make_workspace(gated_client)
    doc2, _ = _make_duplicate(gated_client, monkeypatch, ws)
    r = gated_client(OWNER).post(f"/content-workspaces/{ws}/documents/{doc2}/resolve-duplicate",
                                 json={"action": "explode"})
    assert r.status_code == 422


def test_resolve_duplicate_404s_for_a_nonexistent_document(gated_client):
    ws = _make_workspace(gated_client)
    r = gated_client(OWNER).post(f"/content-workspaces/{ws}/documents/does-not-exist/resolve-duplicate",
                                 json={"action": "cancel"})
    assert r.status_code == 404


def test_resolve_duplicate_409s_when_not_flagged_as_a_duplicate(gated_client, monkeypatch):
    ws = _make_workspace(gated_client)
    doc_id, v1 = _start_upload(gated_client, ws)
    _mock_uploaded(monkeypatch)
    _complete(gated_client, ws, doc_id, v1)  # ordinary, non-duplicate completion

    r = gated_client(OWNER).post(f"/content-workspaces/{ws}/documents/{doc_id}/resolve-duplicate",
                                 json={"action": "cancel"})
    assert r.status_code == 409


def test_resolve_duplicate_keep_as_new_clears_the_flag(gated_client, monkeypatch):
    ws = _make_workspace(gated_client)
    doc2, v2 = _make_duplicate(gated_client, monkeypatch, ws)

    r = gated_client(OWNER).post(f"/content-workspaces/{ws}/documents/{doc2}/resolve-duplicate",
                                 json={"action": "keep_as_new"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ready"
    assert r.json()["versions"][0]["lifecycle_state"] == "ready"

    # still there afterwards, as an ordinary document
    r2 = gated_client(OWNER).get(f"/content-workspaces/{ws}/documents/{doc2}")
    assert r2.status_code == 200
    assert r2.json()["status"] == "ready"


def test_resolve_duplicate_reuse_existing_deletes_the_document(gated_client, monkeypatch):
    ws = _make_workspace(gated_client)
    doc2, _ = _make_duplicate(gated_client, monkeypatch, ws)

    r = gated_client(OWNER).post(f"/content-workspaces/{ws}/documents/{doc2}/resolve-duplicate",
                                 json={"action": "reuse_existing"})
    assert r.status_code == 200, r.text
    assert r.json() == {"document_id": doc2, "status": "deleted", "action": "reuse_existing"}

    r2 = gated_client(OWNER).get(f"/content-workspaces/{ws}/documents/{doc2}")
    assert r2.status_code == 404


def test_resolve_duplicate_cancel_deletes_the_document_and_is_logged_distinctly(
        gated_client, monkeypatch, isolated_store):
    ws = _make_workspace(gated_client)
    doc2, _ = _make_duplicate(gated_client, monkeypatch, ws)

    r = gated_client(OWNER).post(f"/content-workspaces/{ws}/documents/{doc2}/resolve-duplicate",
                                 json={"action": "cancel"})
    assert r.status_code == 200, r.text

    r2 = gated_client(OWNER).get(f"/content-workspaces/{ws}/documents/{doc2}")
    assert r2.status_code == 404

    decisions = isolated_store.list_decisions()
    assert any(d["action"] == "content_workspace.duplicate_cancel" for d in decisions)
    assert not any(d["action"] == "content_workspace.duplicate_reuse_existing" for d in decisions)


def test_resolve_duplicate_404s_for_a_foreign_owner(gated_client, monkeypatch):
    ws = _make_workspace(gated_client, owner=OWNER)
    doc2, _ = _make_duplicate(gated_client, monkeypatch, ws)
    r = gated_client(OTHER).post(f"/content-workspaces/{ws}/documents/{doc2}/resolve-duplicate",
                                 json={"action": "cancel"})
    assert r.status_code == 404


# ── download (PRD "download original") ───────────────────────────────────────

def _download(gated_client, ws, doc_id, version_id, *, owner=OWNER):
    return gated_client(owner).get(
        f"/content-workspaces/{ws}/documents/{doc_id}/versions/{version_id}/download")


def test_download_returns_the_bytes_and_content_type(gated_client, monkeypatch):
    import workspace_blob
    ws = _make_workspace(gated_client)
    doc_id, version_id = _start_upload(gated_client, ws, filename="report.pdf")
    _mock_uploaded(monkeypatch, size=1024, prefix=b"%PDF-1.7")
    _complete(gated_client, ws, doc_id, version_id, content_hash="h1", size_bytes=1024)
    monkeypatch.setattr(workspace_blob, "download_document_bytes",
                        lambda *a, **kw: b"%PDF-1.7 fake pdf bytes")

    r = _download(gated_client, ws, doc_id, version_id)
    assert r.status_code == 200
    assert r.content == b"%PDF-1.7 fake pdf bytes"
    assert r.headers["content-type"] == "application/pdf"
    assert 'filename="report.pdf"' in r.headers["content-disposition"]


def test_download_404s_when_the_blob_is_not_retrievable(gated_client, monkeypatch):
    import workspace_blob
    ws = _make_workspace(gated_client)
    doc_id, version_id = _start_upload(gated_client, ws)
    _mock_uploaded(monkeypatch)
    _complete(gated_client, ws, doc_id, version_id)
    monkeypatch.setattr(workspace_blob, "download_document_bytes", lambda *a, **kw: None)

    r = _download(gated_client, ws, doc_id, version_id)
    assert r.status_code == 404


def test_download_404s_for_a_nonexistent_version(gated_client, monkeypatch):
    ws = _make_workspace(gated_client)
    doc_id, version_id = _start_upload(gated_client, ws)
    _mock_uploaded(monkeypatch)
    _complete(gated_client, ws, doc_id, version_id)

    r = _download(gated_client, ws, doc_id, "does-not-exist")
    assert r.status_code == 404


def test_download_404s_for_a_version_belonging_to_a_different_document(gated_client, monkeypatch):
    ws = _make_workspace(gated_client)
    doc1, v1 = _start_upload(gated_client, ws, filename="a.pdf")
    _mock_uploaded(monkeypatch, size=1024, prefix=b"%PDF-1.7")
    _complete(gated_client, ws, doc1, v1, content_hash="hash-a")
    doc2, _ = _start_upload(gated_client, ws, filename="b.pdf")
    _complete(gated_client, ws, doc2, "v-002", content_hash="hash-b")

    r = _download(gated_client, ws, doc2, v1)  # v1 belongs to doc1, not doc2
    assert r.status_code == 404


def test_download_404s_for_a_foreign_owner(gated_client, monkeypatch):
    ws = _make_workspace(gated_client, owner=OWNER)
    doc_id, version_id = _start_upload(gated_client, ws)
    _mock_uploaded(monkeypatch)
    _complete(gated_client, ws, doc_id, version_id)

    r = _download(gated_client, ws, doc_id, version_id, owner=OTHER)
    assert r.status_code == 404


def test_download_404s_for_a_nonexistent_document(gated_client):
    ws = _make_workspace(gated_client)
    r = _download(gated_client, ws, "does-not-exist", "v1")
    assert r.status_code == 404


def test_download_works_for_a_quarantined_version(gated_client, monkeypatch):
    """Quarantine blocks Discovery, not a user retrieving their own upload — see the route's
    own docstring for why this is a deliberate choice, not an oversight."""
    import workspace_blob
    ws = _make_workspace(gated_client)
    doc_id, version_id = _start_upload(gated_client, ws, filename="report.pdf")
    _mock_uploaded(monkeypatch, size=1024, prefix=b"not a pdf")
    r = _complete(gated_client, ws, doc_id, version_id)
    assert r.json()["status"] == "quarantined"
    monkeypatch.setattr(workspace_blob, "download_document_bytes", lambda *a, **kw: b"bytes")

    r2 = _download(gated_client, ws, doc_id, version_id)
    assert r2.status_code == 200


def test_download_sanitizes_a_filename_containing_a_quote(gated_client, monkeypatch):
    """The stored filename is whatever the client claimed at upload-session time —
    untrusted — and goes straight into a response header, so an embedded quote must not be
    able to break out of the quoted-string. (A raw CR/LF can't reach this point at all: it
    would change the extension _start_upload's own allow-list checks, per
    test_safe_disposition_filename_strips_control_characters below — this test covers what a
    quote alone, which doesn't affect the extension, does.)"""
    import workspace_blob
    ws = _make_workspace(gated_client)
    doc_id, version_id = _start_upload(gated_client, ws, filename='evil".pdf')
    _mock_uploaded(monkeypatch, size=1024, prefix=b"%PDF-1.7")
    _complete(gated_client, ws, doc_id, version_id)
    monkeypatch.setattr(workspace_blob, "download_document_bytes", lambda *a, **kw: b"bytes")

    r = _download(gated_client, ws, doc_id, version_id)
    assert r.status_code == 200
    disposition = r.headers["content-disposition"]
    assert '"' not in disposition.split("filename=", 1)[1][1:-1]


def test_safe_disposition_filename_strips_control_characters():
    import routes.content_workspaces as cw
    cleaned = cw._safe_disposition_filename('evil".pdf\r\nX-Injected: yes')
    assert "\r" not in cleaned
    assert "\n" not in cleaned
    assert '"' not in cleaned


def test_safe_disposition_filename_falls_back_when_nothing_printable_survives():
    import routes.content_workspaces as cw
    assert cw._safe_disposition_filename("\r\n\t") == "download"
