"""Owner-isolation tests for three endpoints identified in the 2026-09-02 audit.

Each section covers one gap:

  Gap 1 — GET /inventory: global path-dedup table, no owner column.
           Before fix: any authenticated user received the full cross-user inventory.
           After fix: 403 for non-admins; 200 only for the configured owner/admin.

  Gap 2 — GET /scans/jobs/{job_id}: no owner check on the job-poll route.
           Before fix: any authenticated user could poll any job_id and read its state.
           After fix: 404 when the job's scan_id does not belong to the caller.

  Gap 3 — POST /scans/{scan_id}/files/{filename:path}/remediate: no owner check.
           Before fix: any authenticated user could mark any file in any scan as
           remediated, corrupting another user's audit trail.
           After fix: 404 when the scan does not belong to the caller.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

OWNER = "owner@example.org"
ALLOWED_NON_OWNER = "other@example.org"
SID = "b3c4d5e6f789"
JOB_ID = "job-abc123"
FILE = "report.docx"


@pytest.fixture()
def gated_client(monkeypatch, isolated_store):
    """TestClient behind the real access gate with a fake token→email mapping.

    Pattern mirrors tests/test_remediated_download_isolation.py so the fixtures
    are directly comparable.  Passing the Bearer token value as-is to
    verify_gis_token makes the token == the email, which is how all route-level
    isolation tests in this codebase work.
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

    def as_user(email: str):
        client.headers.update({"Authorization": f"Bearer {email}"})
        return client

    return as_user


@pytest.fixture()
def seeded_scan(isolated_store):
    """One completed scan owned by OWNER."""
    isolated_store.save_scan({
        "_scan_id": SID,
        "started_at": "2026-09-02T10:00:00+00:00",
        "completed_at": "2026-09-02T10:05:00+00:00",
        "source": "drive",
        "owner": OWNER,
        "rubric": {"name": "wcag-aa", "hash": "h"},
        "summary": {"files": 1, "certifiable": 1, "uncertain": 0, "error": 0, "avg_score": 85},
        "files": [{"file": FILE, "engine": "docx", "status": "certifiable",
                   "score": 85, "compliant": 1, "skipped_rules": 0, "issues": []}],
    })
    return isolated_store


# ── Gap 1: GET /inventory ──────────────────────────────────────────────────────

class TestInventoryAdminGate:
    def test_admin_can_read_global_inventory(self, gated_client):
        """NON-VACUITY: the owner/admin must still be able to read the inventory."""
        res = gated_client(OWNER).get("/inventory")
        assert res.status_code == 200, (
            f"admin cannot reach GET /inventory ({res.status_code}) — "
            "fixture is broken, isolation assertions below would prove nothing")

    def test_non_admin_is_blocked_from_global_inventory(self, gated_client, monkeypatch):
        """THE FIX THIS FILE EXISTS FOR (Gap 1).

        The inventory table holds every file path seen across ALL users (it is a
        global dedup index with no owner column).  Before the fix, any authenticated
        user could call GET /inventory and receive the full cross-account listing —
        including file paths from scans they do not own.

        ACP_OPEN_ACCESS defaults to 1, which makes every authenticated user an admin.
        We disable it here to exercise the role-based admin gate explicitly.
        """
        import core
        monkeypatch.setattr(core, "OPEN_ACCESS", False)
        res = gated_client(ALLOWED_NON_OWNER).get("/inventory")
        assert res.status_code == 403, (
            f"expected 403 for a non-admin caller, got {res.status_code}. "
            "GET /inventory is a global cross-user table; non-admins must be blocked.")

    def test_unauthenticated_caller_is_refused(self, gated_client):
        """Even without a token the gate must refuse (the access gate handles this before
        the route runs, but assert the observable outcome is still not 200)."""
        client = gated_client(OWNER)
        client.headers.pop("Authorization", None)
        res = client.get("/inventory")
        assert res.status_code != 200


# ── Gap 2: GET /scans/jobs/{job_id} ──────────────────────────────────────────

class TestJobPollOwnerIsolation:
    def test_owner_can_poll_their_own_job(self, gated_client, monkeypatch, seeded_scan):
        """NON-VACUITY: the owning user must still be able to poll the job."""
        import core
        job_state = {"phase": "running", "done": False, "scan_id": SID, "seq": 1}
        monkeypatch.setattr(core, "get_job_state", lambda jid: job_state if jid == JOB_ID else None)
        res = gated_client(OWNER).get(f"/scans/jobs/{JOB_ID}")
        assert res.status_code == 200, (
            f"owner cannot poll their own job ({res.status_code}) — fixture broken")

    def test_non_owner_cannot_poll_a_foreign_job(self, gated_client, monkeypatch, seeded_scan):
        """THE FIX THIS FILE EXISTS FOR (Gap 2).

        Before the fix, any authenticated user who knew (or guessed) a job_id could
        poll GET /scans/jobs/{job_id} and read full job state — source paths, file
        counts, phase details — belonging to another user's scan.
        """
        import core
        job_state = {"phase": "running", "done": False, "scan_id": SID, "seq": 1}
        monkeypatch.setattr(core, "get_job_state", lambda jid: job_state if jid == JOB_ID else None)
        res = gated_client(ALLOWED_NON_OWNER).get(f"/scans/jobs/{JOB_ID}")
        assert res.status_code == 404, (
            f"expected 404 for a job whose scan belongs to a different user, got {res.status_code}. "
            "The route must verify the job's scan_id is owned by the requester.")

    def test_job_with_no_scan_id_is_still_readable(self, gated_client, monkeypatch):
        """A job may exist before a scan_id is assigned (early-phase queue jobs).
        Those jobs carry no user data yet and must remain pollable by any auth'd user
        so the UI's progress poller does not break during scan startup.
        """
        import core
        job_state = {"phase": "queued", "done": False, "seq": 0}  # no scan_id key
        monkeypatch.setattr(core, "get_job_state", lambda jid: job_state if jid == JOB_ID else None)
        res = gated_client(ALLOWED_NON_OWNER).get(f"/scans/jobs/{JOB_ID}")
        assert res.status_code == 200, (
            f"a pre-scan-id job must be reachable by any auth'd user ({res.status_code})")

    def test_nonexistent_job_is_404(self, gated_client, monkeypatch):
        import core
        monkeypatch.setattr(core, "get_job_state", lambda jid: None)
        res = gated_client(OWNER).get("/scans/jobs/no-such-job")
        assert res.status_code == 404


# ── Gap 3: POST /scans/{scan_id}/files/{filename:path}/remediate ──────────────

class TestRemediateOwnerIsolation:
    def _url(self, scan_id=SID, filename=FILE):
        return f"/scans/{scan_id}/files/{filename}/remediate"

    def test_owner_can_mark_their_own_file_remediated(self, gated_client, seeded_scan):
        """NON-VACUITY: the owning user must still be able to record a remediation."""
        res = gated_client(OWNER).post(self._url())
        assert res.status_code == 200, (
            f"owner cannot mark their own file remediated ({res.status_code}) — fixture broken")

    def test_non_owner_cannot_mark_a_foreign_file_remediated(self, gated_client, seeded_scan):
        """THE FIX THIS FILE EXISTS FOR (Gap 3).

        Before the fix, any authenticated user could POST to
        /scans/{scan_id}/files/{filename}/remediate and corrupt another user's audit
        trail by marking a file as remediated when the real owner had not fixed it.
        """
        res = gated_client(ALLOWED_NON_OWNER).post(self._url())
        assert res.status_code == 404, (
            f"expected 404 for a scan the caller does not own, got {res.status_code}. "
            "The route must check ownership before recording a remediation.")

    def test_non_owner_gets_same_code_for_wrong_filename(self, gated_client, seeded_scan):
        """A non-owner must not be able to distinguish 'wrong filename' from 'not yours'.

        Different codes would turn the endpoint into an oracle for which files a scan
        contains — itself a disclosure of another user's document inventory.
        """
        real = gated_client(ALLOWED_NON_OWNER).post(self._url())
        fake = gated_client(ALLOWED_NON_OWNER).post(self._url(filename="no-such-file.pdf"))
        assert real.status_code == fake.status_code == 404

    def test_nonexistent_scan_is_404_for_owner(self, gated_client):
        """Sanity: a scan_id that does not exist at all should still yield 404."""
        res = gated_client(OWNER).post(self._url(scan_id="nonexistent-scan-id"))
        assert res.status_code == 404
