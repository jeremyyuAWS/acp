"""lf.fetch_document_history backs the cross-scan "this document over time" panel — the view
Langfuse's own session-grouped UI can't give. It queries the `file:<label>` tag (the same tag
_file_tags writes), so it collects one document across every scan. Pins: newest-first ordering,
the PHI-safe row shape (no name/email, result from output), and the route's honest states."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))
import lf  # noqa: E402


class _Resp:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload

    def json(self):
        return self._payload


def _trace(scan, ts, score, email="jeremy_acp@fgxlxj.onmicrosoft.com"):
    return {"id": f"{scan}::doc-aaa.docx", "name": f"{email} · doc-aaa.docx", "sessionId": scan,
            "timestamp": ts, "input": {"document": "doc-aaa.docx", "format": "docx"},
            "output": {"score": score, "conformant": False, "level": "AA",
                       "failing_criteria": {"1.4.3": 1}}}


# deliberately out of order — the newest (Aug) is listed last
HIST = {"data": [
    _trace("scanA", "2026-06-03T09:00:00Z", 60),
    _trace("scanC", "2026-08-19T17:00:00Z", 82),
    _trace("scanB", "2026-06-10T09:00:00Z", 71),
]}


@pytest.fixture()
def enabled(monkeypatch):
    monkeypatch.setattr(lf, "_ENABLED", True, raising=False)
    monkeypatch.setattr(lf, "_HOST", "https://lf.example", raising=False)
    monkeypatch.setattr(lf, "_PK", "pk", raising=False)
    monkeypatch.setattr(lf, "_SK", "sk", raising=False)


def _patch(monkeypatch, resp, seen=None):
    import httpx
    def fake(url, *a, **k):
        if seen is not None:
            seen["url"] = url
        return resp
    monkeypatch.setattr(httpx, "get", fake)


def test_disabled_returns_none(monkeypatch):
    monkeypatch.setattr(lf, "_ENABLED", False, raising=False)
    assert lf.fetch_document_history("doc-aaa.docx") is None


def test_queries_the_file_tag_not_a_rehash(enabled, monkeypatch):
    seen = {}
    _patch(monkeypatch, _Resp(200, HIST), seen)
    lf.fetch_document_history("doc-aaa.docx")
    # the label is used AS-IS in a file: tag — never re-hashed through _doc_label
    assert "tags=file%3Adoc-aaa.docx" in seen["url"]


def test_rows_are_newest_first_and_carry_no_email(enabled, monkeypatch):
    _patch(monkeypatch, _Resp(200, HIST))
    h = lf.fetch_document_history("doc-aaa.docx")
    assert h["total"] == 3 and h["document"] == "doc-aaa.docx" and h["format"] == "docx"
    order = [r["scan_id"] for r in h["scans"]]
    assert order == ["scanC", "scanB", "scanA"]                 # Aug, then the two Junes
    blob = json.dumps(h, default=str)
    assert "@" not in blob                                      # no operator email survives
    for r in h["scans"]:
        assert set(r.keys()) == {"scan_id", "trace_id", "timestamp", "result"}
        assert r["result"]["score"] in (60, 71, 82)


def test_non_200_returns_none(enabled, monkeypatch):
    _patch(monkeypatch, _Resp(404, {}))
    assert lf.fetch_document_history("doc-aaa.docx") is None


# ── the /history route ──
@pytest.fixture()
def client(monkeypatch, isolated_store):
    import core
    from fastapi.testclient import TestClient

    from app import app

    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setattr(core, "ACCESS_CODE", "", raising=False)
    monkeypatch.setattr(core, "GOOGLE_CLIENT_ID", "", raising=False)
    monkeypatch.setattr(core, "E2E_KEY", None, raising=False)
    monkeypatch.setattr(isolated_store, "get_scan", lambda *a, **k: {"id": "s1"})
    return TestClient(app), isolated_store


def test_route_404_when_scan_missing(client, monkeypatch):
    c, store = client
    monkeypatch.setattr(store, "get_scan", lambda *a, **k: None)
    assert c.get("/scans/nope/trace/file/doc-aaa.docx/history").status_code == 404


def test_route_not_configured(client, monkeypatch):
    c, _ = client
    monkeypatch.setattr(lf, "enabled", lambda: False)
    assert c.get("/scans/s1/trace/file/doc-aaa.docx/history").json() == {"status": "not_configured"}


def test_route_ok_passes_the_label_through(client, monkeypatch):
    c, _ = client
    seen = {}
    monkeypatch.setattr(lf, "enabled", lambda: True)
    monkeypatch.setattr(lf, "fetch_document_history", lambda label, **k: (seen.setdefault("label", label), {"document": label, "total": 0, "scans": []})[1])
    body = c.get("/scans/s1/trace/file/doc-aaa.docx/history").json()
    assert body["status"] == "ok" and body["history"]["document"] == "doc-aaa.docx"
    assert seen["label"] == "doc-aaa.docx"     # the label, not "s1::doc-aaa.docx"
