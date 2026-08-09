"""Can an allow-listed non-owner reach another user's remediated file? (P0.1, the uncovered half)

The 2026-08-08 owner-isolation audit checked five links and concluded there is no IDOR. That
conclusion holds for what it examined — `_owner()` reads `request.state.user_email`, which the
access gate writes from a verified GIS token and nothing else, so no query parameter, path
segment, header or body field can steer it.

But its endpoint list (tests/test_foreign_scan_404.py PER_SCAN_ENDPOINTS) does not include the
remediated-download route, and the audit's own "what this does NOT cover" names blob path
handling. This file covers that gap, because the route has a branch the others do not:

    urls = store.get_remediation_urls(scan_id, filename)   # <- NO owner predicate
    ...
    data = blob.download_remediated(owner, ...)            # scoped: None for a foreign file
    if urls.get("drive_write_url"):
        return RedirectResponse(urls["drive_write_url"])

The blob read is correctly scoped — it is keyed `{owner}/{scan_id}/{filename}` with the CALLER's
owner, so a foreign document is simply absent and returns None. The exposure, if any, is the
fall-through: `urls` came from an unscoped lookup, so the Drive mirror URL in it may belong to
somebody else. Under pytest blob storage is unconfigured, which makes `download_remediated`
return None for everyone and puts every request straight onto that branch — the same state a
production deployment reaches for any file whose remediation predates ADR 0010.

A UUID scan id is not an access control. It leaks into logs, traces, shared links and support
tickets, and "the attacker must know an identifier" is mitigation, not authorisation.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

OWNER = "owner@hospital.org"
ALLOWED_NON_OWNER = "other@hospital.org"
SID = "a242d0f5f635"
FILE = "patient-intake.docx"
SECRET_URL = "https://drive.google.com/file/d/PRIVATE-PHI-DOC/view"


@pytest.fixture()
def gated_client(monkeypatch, isolated_store):
    """A TestClient behind the REAL access gate, with a fake token->email map.

    Faithful to production: ACP_ACCESS_CODE is empty there, so the gate takes the
    `elif core.GOOGLE_CLIENT_ID` branch and stamps request.state.user_email — which is what
    _owner(request) reads. Mirrors tests/test_foreign_scan_404.py's fixture deliberately; if
    that one drifts, these results stop being comparable to it.
    """
    import core
    from fastapi.testclient import TestClient

    from app import app

    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setattr(core, "ACCESS_CODE", "", raising=False)
    monkeypatch.setattr(core, "GOOGLE_CLIENT_ID", "test-client-id", raising=False)
    monkeypatch.setattr(core, "E2E_KEY", None, raising=False)
    monkeypatch.setattr(core, "OWNER_EMAIL", OWNER, raising=False)
    monkeypatch.setattr(core, "verify_gis_token", lambda tok: tok or None)
    monkeypatch.setattr(core, "email_allowed", lambda e: e in (OWNER, ALLOWED_NON_OWNER))

    client = TestClient(app)

    def as_user(email):
        client.headers.update({"Authorization": f"Bearer {email}"})
        return client

    return as_user


@pytest.fixture()
def seeded(isolated_store):
    """One completed scan owned by OWNER, with a remediation recorded as a Drive mirror URL."""
    isolated_store.save_scan({
        # `_scan_id` (not `scan_id`) is the key save_scan pops to reuse a caller-chosen id.
        "_scan_id": SID,
        "started_at": "2026-07-29T21:00:00+00:00",
        "completed_at": "2026-07-29T21:05:00+00:00",
        "source": "drive",
        "owner": OWNER,
        "rubric": {"name": "wcag-aa", "hash": "h"},
        "summary": {"files": 1, "certifiable": 1, "uncertain": 0, "error": 0, "avg_score": 90},
        "files": [{"file": FILE, "engine": "docx", "status": "certifiable",
                   "score": 90, "compliant": 1, "skipped_rules": 0, "issues": []}],
    })
    isolated_store.record_remediation(SID, FILE, drive_write_url=SECRET_URL)
    return isolated_store


def _url(scan_id=SID, filename=FILE) -> str:
    return f"/scans/{scan_id}/files/{filename}/remediated"


def test_owner_can_reach_their_own_remediated_file(gated_client, seeded):
    """NON-VACUITY, first. Without this, a broken fixture would make every isolation
    assertion below pass for the wrong reason — nobody can reach anything."""
    res = gated_client(OWNER).get(_url(), follow_redirects=False)
    assert res.status_code in (200, 302, 307), (
        f"the scan's own owner cannot reach it ({res.status_code}) — the fixture is broken, so "
        "the isolation assertions in this file would prove nothing")


def test_a_non_owner_is_not_handed_the_owners_drive_url(gated_client, seeded):
    """THE FINDING THIS FILE EXISTS FOR.

    The caller does not own the scan. The blob read is correctly scoped and returns None. What
    must NOT happen is the fall-through redirecting them to the owner's Drive copy — that is a
    link to another patient's document, issued to someone the system knows is not entitled to it.
    """
    res = gated_client(ALLOWED_NON_OWNER).get(_url(), follow_redirects=False)

    location = res.headers.get("location") or ""
    assert SECRET_URL not in location, (
        "CROSS-OWNER DISCLOSURE: a non-owner was redirected to the owner's remediated document "
        f"({location!r}). get_remediation_urls has no owner predicate, so the URL it returns can "
        "belong to anybody; the route must resolve ownership before using it.")
    assert res.status_code == 404, (
        f"expected 404 for a scan the caller does not own, got {res.status_code} — 404 rather "
        "than 403 is this codebase's deliberate choice, so a non-owner cannot even confirm the "
        "scan exists (see tests/test_foreign_scan_404.py)")


def test_the_scan_is_invisible_even_when_the_file_name_is_wrong(gated_client, seeded):
    """A non-owner must not be able to distinguish 'wrong filename' from 'not yours'.

    Different status codes for the two cases turn the endpoint into an oracle for which
    documents a scan contains, which is itself disclosure about a patient record.
    """
    real = gated_client(ALLOWED_NON_OWNER).get(_url(), follow_redirects=False)
    fake = gated_client(ALLOWED_NON_OWNER).get(_url(filename="no-such-file.docx"),
                                               follow_redirects=False)
    assert real.status_code == fake.status_code == 404


def test_the_store_layer_refuses_a_foreign_row_on_its_own(seeded):
    """The second of the two independent barriers, checked WITHOUT going through the route.

    The fix added an ownership check to the route AND an owner predicate to the query. Both are
    deliberate, and the comments claim either alone would have stopped the disclosure — so verify
    that instead of asserting it. If a later refactor removes the route check believing the store
    is enough (or vice versa), one of these two tests still fails.
    """
    assert seeded.get_remediation_urls(SID, FILE, owner=OWNER) is not None, (
        "non-vacuity: the owner's own row must still be readable")
    assert seeded.get_remediation_urls(SID, FILE, owner=ALLOWED_NON_OWNER) is None, (
        "a foreign row must not be returned — the predicate filters in SQL, so it is never read "
        "into memory rather than being read and then rejected")
    # Omitting `owner` keeps the old unscoped behaviour for the worker tier, which has no user
    # context. That is why the parameter is optional — and why every request path must pass it.
    assert seeded.get_remediation_urls(SID, FILE) is not None


def test_path_traversal_in_the_filename_cannot_escape_the_owner_prefix(gated_client, seeded):
    """`{filename:path}` accepts slashes, and _blob_path is raw f-string concatenation.

    Azure blob names are flat strings — `..` is not resolved, so a traversal does not reach
    another prefix there. But the same filename also reaches the unscoped DB lookup, and this
    pins that neither route lets a caller read outside their own estate.
    """
    for hostile in ("../owner@hospital.org/a242d0f5f635/patient-intake.docx",
                    "..%2Fowner%40hospital.org%2Fa242d0f5f635%2Fpatient-intake.docx"):
        res = gated_client(ALLOWED_NON_OWNER).get(_url(filename=hostile), follow_redirects=False)
        assert SECRET_URL not in (res.headers.get("location") or ""), hostile
        assert res.status_code in (404, 400), f"{hostile} -> {res.status_code}"
