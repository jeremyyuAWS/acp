"""The 404 body for an unresolvable scan is a contract the SPA reads.

`frontend/src/api.js` distinguishes "this scan is not yours / not there" from every other 404 by
matching `detail == "scan not found"`, and only then evicts the scan on screen and recovers to
one the user can load. It must NOT do that for a per-file or per-trace 404 under a scan the user
does own — that would throw away their scan over a missing thumbnail.

So the string is load-bearing in both directions. These tests pin it, and pin that the other
404s in the same module say something else.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

SCAN_NOT_FOUND = "scan not found"
ROUTES_SCANS = Path(__file__).resolve().parent.parent / "api" / "routes" / "scans.py"

# The per-scan endpoints the client calls, with a scan id that does not exist. Same set as the
# live 404 fan-out in test_foreign_scan_404.py, plus the plain scan read.
CLIENT_ENDPOINTS = [
    ("get", "/scans/nosuchscan00"),
    ("post", "/scans/nosuchscan00/assess?level=AA"),
    ("get", "/scans/nosuchscan00/traces"),
    ("get", "/scans/nosuchscan00/diff?vs=alsonothere0"),
    ("get", "/scans/nosuchscan00/pii"),
    ("post", "/scans/nosuchscan00/drive-token"),
]


@pytest.fixture()
def client(monkeypatch, isolated_store):
    """An ungated TestClient (local-dev shape: no access code, no GIS)."""
    import core
    from fastapi.testclient import TestClient

    from app import app

    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setattr(core, "ACCESS_CODE", "", raising=False)
    monkeypatch.setattr(core, "GOOGLE_CLIENT_ID", "", raising=False)
    monkeypatch.setattr(core, "E2E_KEY", None, raising=False)
    return TestClient(app)


@pytest.mark.parametrize("method,path", CLIENT_ENDPOINTS, ids=[p for _, p in CLIENT_ENDPOINTS])
def test_detail_is_exactly_the_string_the_spa_matches(client, method, path):
    res = getattr(client, method)(path)

    assert res.status_code == 404
    assert res.json()["detail"] == SCAN_NOT_FOUND, (
        f"{method.upper()} {path} changed its 404 body. frontend/src/api.js matches this exact "
        f"string to decide a scan is unloadable; change both or neither."
    )


def test_every_owner_check_in_the_scans_router_uses_that_string():
    """A new per-scan route that words its 404 differently would be silently un-recoverable.

    Matches the house shape — a `get_scan(...) is None` guard followed by its raise — rather than
    every 404 in the file, because the other 404s there are deliberately different (see below).
    """
    src = ROUTES_SCANS.read_text()
    guards = re.findall(
        r"get_scan\([^\n]*\) is None:\s*\n\s*(?:return[^\n]*|raise HTTPException\(404, \"([^\"]+)\")",
        src,
    )
    assert guards, "the guard shape changed — re-derive this test rather than deleting it"
    worded = [g for g in guards if g]
    assert worded, "no owner-check 404 raises found; the regex no longer matches the code"
    assert set(worded) == {SCAN_NOT_FOUND}, (
        f"an owner-check 404 in routes/scans.py says {sorted(set(worded))!r}; the SPA only "
        f"recovers from {SCAN_NOT_FOUND!r}"
    )


def test_the_other_404s_in_the_router_are_distinguishable():
    """The recovery must not trigger on a 404 that isn't about the scan's existence.

    `trace not found`, `tracing is not configured`, `unknown trace kind`, `job not found` all
    live in this router and are all NOT the scan being missing.
    """
    src = ROUTES_SCANS.read_text()
    details = set(re.findall(r"HTTPException\(404, \"([^\"]+)\"", src))

    others = details - {SCAN_NOT_FOUND}
    assert others, "expected other 404 kinds in this router; if they are gone, drop this test"
    for d in others:
        assert d != SCAN_NOT_FOUND
        assert not re.fullmatch(SCAN_NOT_FOUND, d, re.IGNORECASE)
