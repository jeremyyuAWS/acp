"""/monitor/estate — the door the production monitor was missing.

The monitor's deep checks (scripts/monitor.py) are the ones that would have caught 2026-07-29's
sweep collapse. They could not run against production, for two independent reasons, and neither
was visible in the monitor's own output:

  1. They authenticated with X-E2E-Key. core.E2E_KEY is None whenever IS_PROD — see
     tests/test_auth_bypass_gate.py, which asserts exactly that — so the header was refused on
     the one deployment worth monitoring. Setting ACP_E2E_KEY would not have changed it. The
     only thing that would have was ACP_ENABLE_TEST_BYPASS=1 in production, i.e. reopening a
     whole-gate backdoor so a health check could get in.
  2. Even granted entry, they read GET /scans, which is scoped to _owner(request). The keyed
     path never stamps a user_email, so it would have read the 'demo' owner's scans — empty —
     and reported "no completed scans at all" about a perfectly healthy estate.

So the fix is a separate, read-only, count-only route with its own credential. These tests pin
the properties that make that trade sound: it works where the bypass cannot, it is closed by
default, and what it hands over is integers rather than the estate.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

KEY = "m0nitor-k3y"


def _seed_scan(store, sid: str, owner: str, files: int) -> None:
    """A finalized scan of `files` documents, owned by `owner`."""
    store.save_scan({
        "_scan_id": sid,
        "started_at": "2026-07-29T21:00:00+00:00",
        "completed_at": f"2026-07-29T21:{int(sid[-2:]):02d}:00+00:00",
        "source": "drive",
        "owner": owner,
        "rubric": {"name": "wcag-aa", "hash": "h"},
        "summary": {"files": files, "certifiable": files, "uncertain": 0, "error": 0,
                    "avg_score": 90},
        "files": [{"file": f"doc{i}.pdf", "engine": "pdf", "status": "certifiable",
                   "score": 90, "compliant": 1, "skipped_rules": 0, "issues": []}
                  for i in range(files)],
    })


@pytest.fixture()
def prod_client(monkeypatch, isolated_store):
    """A TestClient in PRODUCTION SHAPE: the GIS gate live, the test bypass dead.

    This is the configuration the old deep checks could not get through, so a test that passes
    here is evidence about production rather than about a permissive local default.
    """
    import core
    from fastapi.testclient import TestClient

    from app import app

    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setattr(core, "ACCESS_CODE", "", raising=False)
    monkeypatch.setattr(core, "GOOGLE_CLIENT_ID", "test-client-id", raising=False)
    monkeypatch.setattr(core, "E2E_KEY", None, raising=False)          # as in production
    monkeypatch.setattr(core, "MONITOR_KEY", KEY, raising=False)
    return TestClient(app), isolated_store


def test_the_monitor_gets_in_where_the_e2e_bypass_cannot(prod_client):
    """The regression, stated directly: production shape, no Authorization header, no usable
    X-E2E-Key — and the monitor still gets its numbers."""
    client, store = prod_client
    _seed_scan(store, "scan01", "someone@movate.com", files=258)

    assert client.get("/scans").status_code == 401          # the gate is genuinely live
    res = client.get("/monitor/estate", headers={"X-Monitor-Key": KEY})
    assert res.status_code == 200, res.text
    assert res.json()["scans"]["recent_files"] == [258]


def test_a_missing_or_wrong_key_is_401(prod_client):
    client, _ = prod_client
    assert client.get("/monitor/estate").status_code == 401
    assert client.get("/monitor/estate", headers={"X-Monitor-Key": "wrong"}).status_code == 401


def test_an_unconfigured_deployment_is_503_not_an_open_door(monkeypatch, isolated_store):
    """Unset key must CLOSE the route. The tempting alternative — treat "no key configured" as
    "no auth required" — would publish the estate's shape to the internet, and it is the exact
    shape of the ACP_ENV bug: a security control switched off by the absence of a variable."""
    import core
    from fastapi.testclient import TestClient

    from app import app

    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setattr(core, "MONITOR_KEY", None, raising=False)
    client = TestClient(app)
    # 503, distinct from the 401 of a wrong key: the monitor tells the operator which side to fix.
    assert client.get("/monitor/estate").status_code == 503
    assert client.get("/monitor/estate", headers={"X-Monitor-Key": KEY}).status_code == 503


def test_it_counts_every_owner_not_just_the_caller(prod_client):
    """The second half of the old bug. A monitor asks about the DEPLOYMENT; scoping its view to
    one owner is what made the check read an empty 'demo' inbox and call the estate missing."""
    client, store = prod_client
    _seed_scan(store, "scan01", "alice@movate.com", files=258)
    _seed_scan(store, "scan02", "bob@movate.com", files=11)

    body = client.get("/monitor/estate", headers={"X-Monitor-Key": KEY}).json()
    assert body["scans"]["total"] == 2
    assert sorted(body["scans"]["recent_files"]) == [11, 258]


def test_the_collapse_is_visible_in_what_it_returns(prod_client, monkeypatch):
    """End to end with the real check: the monitor's policy must fire on data this route
    actually produces, not only on a hand-written fixture.

    tests/test_monitor.py drives check_estate from a literal payload, which proves the policy
    but assumes the shape. This closes that gap — the two could drift apart silently, and the
    resulting monitor would pass its own tests while reading production wrong.
    """
    sys.path.insert(0, str(ACP / "scripts"))
    import monitor as M

    client, store = prod_client
    _seed_scan(store, "scan01", "alice@movate.com", files=258)
    _seed_scan(store, "scan02", "alice@movate.com", files=258)
    _seed_scan(store, "scan03", "alice@movate.com", files=1)     # the sweep lands on top

    res = client.get("/monitor/estate", headers={"X-Monitor-Key": KEY})
    monkeypatch.setattr(M, "get", lambda url, key=None, timeout=20: (res.status_code, res.text, 1.0))
    rep = M.Report()
    M.check_estate("https://x", KEY, rep)
    assert rep.failed == 1
    assert any("newest has 1 documents but a recent scan had 258" in r[2] for r in rep.rows)


def test_it_hands_over_counts_and_nothing_else(prod_client):
    """The justification for a public-path credential is that losing it costs a few integers.
    If filenames or owner emails ever appear here, that argument is gone."""
    client, store = prod_client
    _seed_scan(store, "scan01", "alice@movate.com", files=2)

    raw = client.get("/monitor/estate", headers={"X-Monitor-Key": KEY}).text
    assert "alice@movate.com" not in raw
    assert "doc0.pdf" not in raw
    assert "@" not in raw and ".pdf" not in raw
