"""An allow-listed non-owner holding someone else's scan id gets 404 on every endpoint.

Reproduces the production failure from 2026-07-29 (app v2026.7.29.5): an allowed user could
not get a score on Assess. Every request for one scan id 404'd —

    POST /scans/<sid>/assess?level=AA   404
    GET  /scans/<sid>/traces            404
    GET  /scans/<sid>/diff?vs=<other>   404
    GET  /scans/<sid>/pii               404
    POST /scans/<sid>/drive-token       404

— while assess against a scan of his own returned 200 in the same minute. Scoring was never
broken; the scan was not resolvable for that session.

The 404 is CORRECT and intended. Per-user isolation (0a1b167, "so one person never sees
another's scans") scopes every per-scan read to `owner_email`, and returns 404 rather than 403
so a scan id is not an existence oracle across tenants. These tests pin that behaviour so it
is not "fixed" into a cross-tenant read. The defect is the client's: it held an id it could
never load and retried invisibly. See test_active_scan_recovery.py for that half.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

OWNER = "jeremyyu.movate@gmail.com"
ALLOWED_NON_OWNER = "devamovate@gmail.com"

# The five endpoints the live client hit, as (method, path template).
PER_SCAN_ENDPOINTS = [
    ("post", "/scans/{sid}/assess?level=AA"),
    ("get", "/scans/{sid}/traces"),
    ("get", "/scans/{sid}/diff?vs={other}"),
    ("get", "/scans/{sid}/pii"),
    ("post", "/scans/{sid}/drive-token"),
    # get_scan(sid) here had no owner predicate — an allowed non-owner holding (or guessing)
    # another tenant's scan id could enqueue remediate_file jobs against it. Found 2026-08-27
    # auditing get_scan() call sites while investigating an unrelated cross-tenant monitor
    # false-positive; scan ids are random 12-hex-char strings so not practically guessable, but
    # the same isolation invariant as the other five applies regardless.
    ("post", "/scans/{sid}/remediate"),
]


def _seed_scan(store, sid: str, owner: str) -> None:
    """A finalized scan with one assessed file, owned by `owner`."""
    # `_scan_id` (not `scan_id`) is the key save_scan pops to reuse a caller-chosen id.
    store.save_scan({
        "_scan_id": sid,
        "started_at": "2026-07-29T21:00:00+00:00",
        "completed_at": "2026-07-29T21:05:00+00:00",
        "source": "drive",
        "owner": owner,
        "rubric": {"name": "wcag-aa", "hash": "h"},
        "summary": {"files": 1, "certifiable": 1, "uncertain": 0, "error": 0, "avg_score": 90},
        "files": [{"file": "report.pdf", "engine": "pdf", "status": "certifiable",
                   "score": 90, "compliant": 1, "skipped_rules": 0, "issues": []}],
    })


@pytest.fixture()
def gated_client(monkeypatch, isolated_store):
    """A TestClient behind the real GIS access gate, with a fake token→email map.

    Faithful to production: ACP_ACCESS_CODE is empty there (verified on the live container
    app), so the gate takes the `elif core.GOOGLE_CLIENT_ID` branch and stamps
    request.state.user_email — which is what _owner(request) reads.
    """
    import core
    from fastapi.testclient import TestClient

    from app import app

    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setattr(core, "ACCESS_CODE", "", raising=False)
    monkeypatch.setattr(core, "GOOGLE_CLIENT_ID", "test-client-id", raising=False)
    monkeypatch.setattr(core, "E2E_KEY", None, raising=False)
    monkeypatch.setattr(core, "OWNER_EMAIL", OWNER, raising=False)
    # token == email, so a test can sign in as anybody without touching Google.
    monkeypatch.setattr(core, "verify_gis_token", lambda tok: tok or None)
    monkeypatch.setattr(core, "email_allowed", lambda e: e in (OWNER, ALLOWED_NON_OWNER))

    client = TestClient(app)

    def as_user(email):
        client.headers.update({"Authorization": f"Bearer {email}"})
        return client

    return as_user


@pytest.mark.parametrize("method,path", PER_SCAN_ENDPOINTS,
                         ids=[p.split("/")[-1] for _, p in PER_SCAN_ENDPOINTS])
def test_every_per_scan_endpoint_404s_for_an_allowed_non_owner(
        gated_client, isolated_store, method, path):
    """The production symptom, endpoint by endpoint."""
    _seed_scan(isolated_store, "a242d0f5f635", OWNER)          # the owner's scan
    _seed_scan(isolated_store, "d0947e87ab4f", OWNER)          # the ?vs= baseline

    url = path.format(sid="a242d0f5f635", other="d0947e87ab4f")

    # Non-vacuity first: the OWNER must not get 404 on this exact URL. Without this, a seed
    # that silently failed to create the scan would make every assertion below pass for the
    # wrong reason — which is exactly what happened on the first draft of this test.
    owner_res = getattr(gated_client(OWNER), method)(url)
    assert owner_res.status_code != 404, (
        f"{method.upper()} {url} 404s for the scan's own owner — the fixture is broken, so the "
        f"non-owner assertion below would prove nothing"
    )

    res = getattr(gated_client(ALLOWED_NON_OWNER), method)(url)

    assert res.status_code == 404, (
        f"{method.upper()} {url} returned {res.status_code}; a non-owner must not read "
        f"another user's scan, and must not be told it exists either"
    )


def test_the_same_endpoint_succeeds_against_the_callers_own_scan(gated_client, isolated_store):
    """The contrast that proves the assess path itself is fine.

    Live evidence: POST /scans/655c0ace429b/assess?level=AA returned 200 three times in the
    same window the other scan was 404ing.
    """
    _seed_scan(isolated_store, "655c0ace429b", ALLOWED_NON_OWNER)

    res = gated_client(ALLOWED_NON_OWNER).post("/scans/655c0ace429b/assess?level=AA")

    assert res.status_code == 200
    assert res.json()["scan_id"] == "655c0ace429b"


def test_the_owner_can_still_read_their_own_scan(gated_client, isolated_store):
    """Isolation is per-user, not a blanket refusal — the owner is unaffected."""
    _seed_scan(isolated_store, "a242d0f5f635", OWNER)

    res = gated_client(OWNER).get("/scans/a242d0f5f635")

    assert res.status_code == 200
    assert res.json()["run"]["owner_email"] == OWNER


def test_a_non_owner_scan_is_absent_from_the_list_not_merely_unreadable(
        gated_client, isolated_store):
    """`GET /scans` must not offer an id that `GET /scans/{id}` will refuse.

    This is the invariant the client can rely on to recover: everything the list returns is
    loadable. A client that instead remembers an id across sign-ins has no such guarantee.
    """
    _seed_scan(isolated_store, "a242d0f5f635", OWNER)
    _seed_scan(isolated_store, "655c0ace429b", ALLOWED_NON_OWNER)

    listed = gated_client(ALLOWED_NON_OWNER).get("/scans").json()

    ids = [s["id"] for s in listed]
    assert ids == ["655c0ace429b"]
    assert "a242d0f5f635" not in ids


def test_owner_only_admin_endpoints_403_for_an_allowed_non_owner(gated_client, isolated_store):
    """The corroborating signal from the same session: 403, not 404.

    Under the open-access model an allowed non-owner is a full admin for VIEWS — so the provider
    and approval-queue reads below now return 200, not 403 (everyone sees the same screens). The
    403 gate still exists, on the DESTRUCTIVE owner-only actions: wiping data, managing logins,
    approving a move/trash. Pinned alongside the 404s because the pair is what identifies the
    situation in a log: 403 means "you are known and not the owner (of this destructive action)",
    404 means "this scan is not yours". Two different gates, both working.
    """
    client = gated_client(ALLOWED_NON_OWNER)

    # Views are open to any signed-in user now.
    assert client.get("/ai/providers").status_code == 200
    assert client.get("/disposition/approvals").status_code == 200
    # The destructive/perimeter actions stay owner-only → 403 for an allowed non-owner.
    assert client.put("/admin/admins", json={"emails": []}).status_code == 403
    assert client.post("/admin/reset?confirm=true").status_code == 403
