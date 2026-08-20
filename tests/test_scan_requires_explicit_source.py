"""A scan must name its source explicitly — 'local' is no longer a silent default.

'local' scans the bundled test corpus, not the production estate. A source-less scan that defaulted
to it produced a small scan that landed as 'latest' and collapsed every dashboard/report/selector
(the fingerprint the production probe caught). So the source is now required at the HTTP boundary and
the worker fails closed on a source-less job. 'local' stays reachable when explicitly asked for.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))

import handlers  # noqa: E402
from worker import FatalJobError  # noqa: E402


# ── the worker: fail closed, do not scan the bundled corpus ───────────────────

def test_worker_fails_closed_on_a_sourceless_scan_job():
    # Reaches the source check before any scan work (right after the scan_id check), so no store or
    # corpus access happens — it raises instead of quietly scanning test files.
    with pytest.raises(FatalJobError, match="source"):
        handlers._scan({"scan_id": "s1"}, {})


# ── the HTTP boundary: source is a required, validated query param ────────────

@pytest.fixture
def client(monkeypatch, isolated_store):
    import core
    monkeypatch.setattr(core, "store", isolated_store)
    from fastapi.testclient import TestClient
    from app import app
    return TestClient(app)


def test_post_scans_requires_a_source(client):
    # Missing source is a 422 at parameter validation — never a silent local-corpus scan.
    r = client.post("/scans")
    assert r.status_code == 422
    assert "source" in str(r.json())


def test_post_scans_still_rejects_an_unknown_source(client):
    # The allowed set is unchanged (local|drive|sharepoint) — so 'local' remains a valid explicit
    # value; only the silent DEFAULT was removed. An out-of-set value is still a 422.
    r = client.post("/scans?source=bogus")
    assert r.status_code == 422
