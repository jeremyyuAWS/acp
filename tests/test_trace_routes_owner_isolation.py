"""Regression tests for Langfuse trace route owner isolation.

Each trace endpoint must:
  1. Resolve the owner from the request (gate-verified email or "demo").
  2. Call get_scan(sid, owner=owner) — another owner receives 404, not 403 or the scan.
  3. Never return scan data for a different owner.

The /exists variants return {available: False} instead of 404 when the scan
is not found (they are best-effort UI hints, not authoritative gates).

The /history endpoint must forward owner_key to lf.fetch_document_history
so cross-tenant traces are never returned.
"""
from __future__ import annotations
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Minimal fixtures
# ---------------------------------------------------------------------------

OWNER_A = "alice@example.com"
OWNER_B = "bob@example.com"
SCAN_A = "scan-aaaa"
SCAN_B = "scan-bbbb"

_SCAN_STORE: dict[tuple[str, str], dict] = {
    (SCAN_A, OWNER_A): {"scan_id": SCAN_A, "run": {"owner_email": OWNER_A}},
    (SCAN_A, "demo"): {"scan_id": SCAN_A, "run": {"owner_email": OWNER_A}},  # keyless
    (SCAN_B, OWNER_B): {"scan_id": SCAN_B, "run": {"owner_email": OWNER_B}},
}


def _get_scan(sid: str, owner: str | None = None) -> dict | None:
    """Mimic store.get_scan(sid, owner=owner) — None when owner mismatches."""
    return _SCAN_STORE.get((sid, owner or "demo"))


# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

def _make_app(user_email: str | None) -> FastAPI:
    """Build a minimal FastAPI app with the scans router and a request-state middleware
    that stamps user_email (mimicking the auth gate)."""
    from fastapi import FastAPI
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request

    app = FastAPI()

    class _Auth(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            request.state.user_email = user_email
            return await call_next(request)

    app.add_middleware(_Auth)

    import routes.scans as scans_mod
    app.include_router(scans_mod.router)
    return app


def _client(user_email: str | None) -> TestClient:
    app = _make_app(user_email)
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Helpers that patch the right objects for all trace endpoints
# ---------------------------------------------------------------------------

def _lf_disabled():
    """Patch lf so tracing is disabled — routes that check enabled() return not_configured."""
    return patch("lf.enabled", return_value=False)


# ---------------------------------------------------------------------------
# Owner isolation: correct owner gets 200/not_configured; wrong owner gets 404
# ---------------------------------------------------------------------------

REDIRECT_PATHS = [
    f"/scans/{SCAN_A}/trace/session",
    f"/scans/{SCAN_A}/trace/scan",
    f"/scans/{SCAN_A}/trace/file/doc-abc123.docx",
]

DATA_PATHS = [
    f"/scans/{SCAN_A}/trace/session/data",
    f"/scans/{SCAN_A}/trace/file/doc-abc123.docx/data",
    f"/scans/{SCAN_A}/trace/file/doc-abc123.docx/history",
]

# /trace/{kind}/exists returns {available: false} (200) — best-effort UI hint, not auth gate.
# /trace/file/.../exists is SHADOWED by the greedy open_file_trace route (registered first),
# so it also returns 404 for a wrong owner — the SPA treats that as "not available".
EXISTS_KIND_PATHS = [f"/scans/{SCAN_A}/trace/scan/exists"]
EXISTS_FILE_PATH = f"/scans/{SCAN_A}/trace/file/doc-abc123.docx/exists"


@pytest.mark.parametrize("path", DATA_PATHS + REDIRECT_PATHS + [EXISTS_FILE_PATH])
def test_wrong_owner_gets_404(path):
    """A request authenticated as owner B must receive 404 for owner A's scan."""
    with patch("core.store") as mock_store, _lf_disabled():
        mock_store.get_scan.side_effect = _get_scan
        c = _client(OWNER_B)
        resp = c.get(path, follow_redirects=False)
    assert resp.status_code == 404, f"{path}: expected 404, got {resp.status_code}"


@pytest.mark.parametrize("path", EXISTS_KIND_PATHS)
def test_wrong_owner_kind_exists_returns_false(path):
    """/trace/{kind}/exists returns {available: false} (not 404) for another owner's scan."""
    with patch("core.store") as mock_store, _lf_disabled():
        mock_store.get_scan.side_effect = _get_scan
        c = _client(OWNER_B)
        resp = c.get(path)
    assert resp.status_code == 200
    assert resp.json() == {"available": False}


@pytest.mark.parametrize("path", DATA_PATHS)
def test_correct_owner_gets_through(path):
    """Owner A's request must NOT get a 404 for their own scan (may get not_configured)."""
    with patch("core.store") as mock_store, _lf_disabled():
        mock_store.get_scan.side_effect = _get_scan
        c = _client(OWNER_A)
        resp = c.get(path, follow_redirects=False)
    # 200 with not_configured, or 302 redirect — but never 404
    assert resp.status_code != 404, f"{path}: owner A should not get 404 for their own scan"


# ---------------------------------------------------------------------------
# Unknown scan always 404 regardless of owner
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path", DATA_PATHS)
def test_nonexistent_scan_always_404(path):
    path = path.replace(SCAN_A, "scan-does-not-exist")
    with patch("core.store") as mock_store, _lf_disabled():
        mock_store.get_scan.return_value = None
        c = _client(OWNER_A)
        resp = c.get(path)
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# file_trace_history must forward owner_key to fetch_document_history
# ---------------------------------------------------------------------------

def test_file_trace_history_passes_owner_key():
    """fetch_document_history must be called with owner_key so cross-tenant history is filtered."""
    import lf as lf_mod

    fake_history = {"document": "doc-abc123.docx", "format": "docx", "total": 1,
                    "scans": [{"scan_id": SCAN_A, "trace_id": "t1",
                               "timestamp": "2026-01-01T00:00:00Z", "result": None}]}

    with patch("core.store") as mock_store, \
         patch.object(lf_mod, "enabled", return_value=True), \
         patch.object(lf_mod, "fetch_document_history", return_value=fake_history) as mock_hist, \
         patch.object(lf_mod, "_owner_key", wraps=lf_mod._owner_key) as mock_key:

        mock_store.get_scan.side_effect = _get_scan
        c = _client(OWNER_A)
        resp = c.get(f"/scans/{SCAN_A}/trace/file/doc-abc123.docx/history")

    assert resp.status_code == 200, resp.text
    assert mock_hist.called, "fetch_document_history was not called"
    _, kwargs = mock_hist.call_args
    assert "owner_key" in kwargs, "owner_key not forwarded to fetch_document_history"
    # The owner_key must be non-None and non-empty
    assert kwargs["owner_key"], "owner_key must be a non-empty HMAC string"


def test_file_trace_history_wrong_owner_does_not_call_fetch():
    """fetch_document_history must NOT be called when the scan belongs to another owner."""
    import lf as lf_mod

    with patch("core.store") as mock_store, \
         patch.object(lf_mod, "enabled", return_value=True), \
         patch.object(lf_mod, "fetch_document_history") as mock_hist:

        mock_store.get_scan.side_effect = _get_scan
        c = _client(OWNER_B)
        resp = c.get(f"/scans/{SCAN_A}/trace/file/doc-abc123.docx/history")

    assert resp.status_code == 404
    mock_hist.assert_not_called()


# ---------------------------------------------------------------------------
# lf._owner_key: stable, non-empty, no raw email
# ---------------------------------------------------------------------------

def test_owner_key_is_stable():
    import lf as lf_mod
    k1 = lf_mod._owner_key(OWNER_A)
    k2 = lf_mod._owner_key(OWNER_A)
    assert k1 == k2, "_owner_key must be deterministic"


def test_owner_key_differs_by_owner():
    import lf as lf_mod
    assert lf_mod._owner_key(OWNER_A) != lf_mod._owner_key(OWNER_B)


def test_owner_key_does_not_contain_email():
    import lf as lf_mod
    key = lf_mod._owner_key(OWNER_A)
    assert OWNER_A not in key
    assert "@" not in key


def test_owner_key_starts_with_prefix():
    import lf as lf_mod
    assert lf_mod._owner_key(OWNER_A).startswith("owner-")


def test_owner_key_none_is_demo():
    import lf as lf_mod
    assert lf_mod._owner_key(None) == lf_mod._owner_key("demo")


# ---------------------------------------------------------------------------
# lf._file_tags: no raw email in tags
# ---------------------------------------------------------------------------

def test_file_tags_no_raw_email():
    import lf as lf_mod
    tags = lf_mod._file_tags("report.docx", OWNER_A)
    for tag in tags:
        assert OWNER_A not in tag, f"raw email found in tag: {tag!r}"
        assert "@" not in tag, f"email address found in tag: {tag!r}"


def test_file_tags_contains_owner_prefix():
    import lf as lf_mod
    tags = lf_mod._file_tags("report.docx", OWNER_A)
    owner_tags = [t for t in tags if t.startswith("owner:")]
    assert len(owner_tags) == 1, f"expected exactly one owner: tag, got {tags}"


# ---------------------------------------------------------------------------
# fetch_document_history: owner_key adds a filter tag to the query
# ---------------------------------------------------------------------------

def test_fetch_document_history_appends_owner_tag(monkeypatch):
    """When owner_key is supplied the URL must contain tags=owner%3A<key>."""
    import lf as lf_mod

    captured = {}

    class FakeResp:
        status_code = 200
        def json(self): return {"data": []}

    def fake_get(url, **kw):
        captured["url"] = url
        return FakeResp()

    monkeypatch.setattr(lf_mod, "_ENABLED", True)
    monkeypatch.setattr(lf_mod, "_HOST", "https://lf.example.com")
    monkeypatch.setattr(lf_mod, "_PK", "pk")
    monkeypatch.setattr(lf_mod, "_SK", "sk")

    import urllib.parse
    with patch("httpx.get", side_effect=fake_get):
        lf_mod.fetch_document_history("doc-abc123.docx", owner_key="owner-abc123def456")

    url = captured.get("url", "")
    assert "tags=" in url
    assert urllib.parse.quote("owner:owner-abc123def456", safe="") in url


def test_fetch_document_history_no_owner_key_omits_owner_tag(monkeypatch):
    """Without owner_key the query must NOT include any owner: tag (backward compat)."""
    import lf as lf_mod

    captured = {}

    class FakeResp:
        status_code = 200
        def json(self): return {"data": []}

    def fake_get(url, **kw):
        captured["url"] = url
        return FakeResp()

    monkeypatch.setattr(lf_mod, "_ENABLED", True)
    monkeypatch.setattr(lf_mod, "_HOST", "https://lf.example.com")
    monkeypatch.setattr(lf_mod, "_PK", "pk")
    monkeypatch.setattr(lf_mod, "_SK", "sk")

    with patch("httpx.get", side_effect=fake_get):
        lf_mod.fetch_document_history("doc-abc123.docx")

    url = captured.get("url", "")
    assert "owner" not in url, f"owner tag must not appear when owner_key is None: {url}"
