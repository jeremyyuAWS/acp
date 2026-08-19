"""lf.fetch_session backs the IN-APP session panel: the whole scan's traces as a PHI-safe list
plus a scan-level rollup, so ACP renders the aggregate that used to hang Langfuse's own UI on
large scans. Pins: the operator email in each trace name never leaves; the rollup counts match
the rows; worst-scoring documents sort first; unassessed files sort last; and the list is capped
(honestly, via total/truncated) while the rollup covers everything."""
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


def _trace(doc, fmt, out, *, email="jeremyyu.movate@gmail.com"):
    return {"id": f"scan-1::{doc}", "name": f"{email} · {doc}", "sessionId": "scan-1",
            "input": {"document": doc, "format": fmt}, "output": out}


SESSION = {"id": "scan-1", "traces": [
    _trace("doc-aaa.docx", "docx", {"score": 67, "conformant": False, "level": "AA",
           "failing_criteria": {"1.1.1": 2}, "pii": {"flagged": True, "types": ["us_ssn"]}}),
    _trace("doc-bbb.pdf", "pdf", {"score": 91, "conformant": True, "level": "AA",
           "failing_criteria": {}}),
    _trace("doc-ccc.xlsx", "xlsx", None),   # discover-only, not assessed
    _trace("doc-ddd.docx", "docx", {"score": 40, "conformant": False, "level": "AA",
           "failing_criteria": {"1.4.3": 1, "2.4.6": 1}, "pii": {"flagged": False, "types": []}}),
]}


@pytest.fixture()
def enabled(monkeypatch):
    monkeypatch.setattr(lf, "_ENABLED", True, raising=False)
    monkeypatch.setattr(lf, "_HOST", "https://lf.example", raising=False)
    monkeypatch.setattr(lf, "_PK", "pk", raising=False)
    monkeypatch.setattr(lf, "_SK", "sk", raising=False)


def _patch(monkeypatch, resp):
    import httpx
    monkeypatch.setattr(httpx, "get", lambda *a, **k: resp)


def test_disabled_returns_none(monkeypatch):
    monkeypatch.setattr(lf, "_ENABLED", False, raising=False)
    assert lf.fetch_session("scan-1") is None


def test_non_200_returns_none(enabled, monkeypatch):
    _patch(monkeypatch, _Resp(404, {}))
    assert lf.fetch_session("scan-1") is None


def test_rows_are_document_format_result_only_no_email(enabled, monkeypatch):
    _patch(monkeypatch, _Resp(200, SESSION))
    s = lf.fetch_session("scan-1")
    blob = json.dumps(s, default=str)
    assert "jeremyyu.movate@gmail.com" not in blob
    for f in s["files"]:
        assert set(f.keys()) == {"trace_id", "document", "format", "result"}


def test_rollup_counts_match_the_rows(enabled, monkeypatch):
    _patch(monkeypatch, _Resp(200, SESSION))
    r = lf.fetch_session("scan-1")["rollup"]
    assert r["documents"] == 4
    assert r["assessed"] == 3            # ccc has no result
    assert r["conformant"] == 1          # only bbb
    assert r["with_failures"] == 2       # aaa + ddd have non-empty failing_criteria
    assert r["with_pii"] == 1            # only aaa flagged
    assert r["avg_score"] == round((67 + 91 + 40) / 3, 1)


def test_worst_score_first_unassessed_last(enabled, monkeypatch):
    _patch(monkeypatch, _Resp(200, SESSION))
    order = [f["document"] for f in lf.fetch_session("scan-1")["files"]]
    assert order == ["doc-ddd.docx", "doc-aaa.docx", "doc-bbb.pdf", "doc-ccc.xlsx"]


def test_list_is_capped_but_rollup_is_not(enabled, monkeypatch):
    _patch(monkeypatch, _Resp(200, SESSION))
    s = lf.fetch_session("scan-1", limit=2)
    assert s["total"] == 4 and s["truncated"] is True
    assert len(s["files"]) == 2
    assert s["rollup"]["documents"] == 4          # rollup still counts all four


# ── the /trace/session/data route ──
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
    assert c.get("/scans/nope/trace/session/data").status_code == 404


def test_route_not_configured(client, monkeypatch):
    c, _ = client
    monkeypatch.setattr(lf, "enabled", lambda: False)
    assert c.get("/scans/s1/trace/session/data").json() == {"status": "not_configured"}


def test_route_ok_wraps_session(client, monkeypatch):
    c, _ = client
    monkeypatch.setattr(lf, "enabled", lambda: True)
    monkeypatch.setattr(lf, "fetch_session", lambda sid, **k: {"id": sid, "total": 0, "files": [], "rollup": {}})
    body = c.get("/scans/s1/trace/session/data").json()
    assert body["status"] == "ok" and body["session"]["id"] == "s1"


def test_route_pending_when_session_none(client, monkeypatch):
    c, _ = client
    monkeypatch.setattr(lf, "enabled", lambda: True)
    monkeypatch.setattr(lf, "fetch_session", lambda sid, **k: None)
    assert c.get("/scans/s1/trace/session/data").json() == {"status": "pending"}
