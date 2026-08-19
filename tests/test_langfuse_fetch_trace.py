"""lf.fetch_trace is the payload behind the IN-APP trace panel (TracePanel): ACP fetches a
trace server-side with its own keys and renders it inside the app, because Langfuse's own
page hangs for a logged-out visitor on our self-hosted v3 and can't be iframed.

Two things this pins, both load-bearing for privacy:
  1. the trace NAME never leaves fetch_trace — it carries the operator's email; and
  2. observations are reduced to structural fields only (no raw input/output/metadata blobs),
     so nothing that could carry document content rides out to the panel.
Plus the ordinary normalization the panel depends on (document/format from input, result from
output, timeline sorted, v3/legacy token-usage field names both mapped)."""
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


RAW = {
    "id": "scan-1::doc-3f9a2c.docx",
    # the name is where the operator email hides — must be dropped
    "name": "jeremyyu.movate@gmail.com · doc-3f9a2c.docx",
    "timestamp": "2026-06-29T17:04:10Z",
    "input": {"document": "doc-3f9a2c.docx", "format": "docx"},
    "output": {"score": 82, "conformant": False, "level": "AA",
               "failing_criteria": {"1.4.3": 2}, "pii": {"flagged": True, "types": ["us_ssn"]}},
    "observations": [
        # deliberately out of order + carrying a raw blob that must NOT survive
        {"type": "GENERATION", "name": "alt-text", "startTime": "2026-06-29T17:04:14Z",
         "endTime": "2026-06-29T17:04:16Z", "model": "llava:13b",
         "usage": {"input": 512, "output": 48}, "calculatedTotalCost": 0.0011,
         "input": {"secret": "PATIENT NAME Jane Roe"}, "output": {"blob": "free text"}},
        {"type": "SPAN", "name": "Discover", "startTime": "2026-06-29T17:04:10Z",
         "endTime": "2026-06-29T17:04:11Z", "level": "DEFAULT",
         # legacy usage field names
         "usage": {"promptTokens": 0, "completionTokens": 0}},
    ],
}


@pytest.fixture()
def enabled(monkeypatch):
    monkeypatch.setattr(lf, "_ENABLED", True, raising=False)
    monkeypatch.setattr(lf, "_HOST", "https://lf.example", raising=False)
    monkeypatch.setattr(lf, "_PK", "pk", raising=False)
    monkeypatch.setattr(lf, "_SK", "sk", raising=False)


def _patch_get(monkeypatch, resp):
    import httpx
    monkeypatch.setattr(httpx, "get", lambda *a, **k: resp)


def test_disabled_returns_none(monkeypatch):
    monkeypatch.setattr(lf, "_ENABLED", False, raising=False)
    assert lf.fetch_trace("scan-1::doc-3f9a2c.docx") is None


def test_non_200_returns_none(enabled, monkeypatch):
    _patch_get(monkeypatch, _Resp(401, {}))
    assert lf.fetch_trace("scan-1::doc-3f9a2c.docx") is None


def test_document_and_format_come_from_input(enabled, monkeypatch):
    _patch_get(monkeypatch, _Resp(200, RAW))
    t = lf.fetch_trace("scan-1::doc-3f9a2c.docx")
    assert t["document"] == "doc-3f9a2c.docx"
    assert t["format"] == "docx"


def test_result_is_the_trace_output(enabled, monkeypatch):
    _patch_get(monkeypatch, _Resp(200, RAW))
    t = lf.fetch_trace("scan-1::doc-3f9a2c.docx")
    assert t["result"]["score"] == 82 and t["result"]["conformant"] is False


def test_trace_name_and_operator_email_never_leave(enabled, monkeypatch):
    _patch_get(monkeypatch, _Resp(200, RAW))
    t = lf.fetch_trace("scan-1::doc-3f9a2c.docx")
    assert "name" not in t
    assert "jeremyyu.movate@gmail.com" not in json.dumps(t, default=str)


def test_observations_carry_no_raw_input_output_blobs(enabled, monkeypatch):
    _patch_get(monkeypatch, _Resp(200, RAW))
    t = lf.fetch_trace("scan-1::doc-3f9a2c.docx")
    blob = json.dumps(t, default=str)
    assert "PATIENT NAME" not in blob and "free text" not in blob
    for o in t["observations"]:
        assert set(o.keys()) == {"type", "name", "start", "end", "level", "status",
                                 "model", "input_tokens", "output_tokens", "cost"}


def test_timeline_is_sorted_by_start_time(enabled, monkeypatch):
    _patch_get(monkeypatch, _Resp(200, RAW))
    t = lf.fetch_trace("scan-1::doc-3f9a2c.docx")
    names = [o["name"] for o in t["observations"]]
    assert names == ["Discover", "alt-text"]   # Discover starts earlier despite being listed 2nd


def test_usage_field_names_both_map(enabled, monkeypatch):
    _patch_get(monkeypatch, _Resp(200, RAW))
    t = lf.fetch_trace("scan-1::doc-3f9a2c.docx")
    by = {o["name"]: o for o in t["observations"]}
    assert by["alt-text"]["input_tokens"] == 512 and by["alt-text"]["output_tokens"] == 48
    assert by["alt-text"]["cost"] == 0.0011
    assert by["Discover"]["input_tokens"] == 0 and by["Discover"]["output_tokens"] == 0


# ── the /trace/file/{file}/data route: honest states, never a 500 for a missing trace ──
@pytest.fixture()
def client(monkeypatch, isolated_store):
    import core
    from fastapi.testclient import TestClient

    from app import app

    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setattr(core, "ACCESS_CODE", "", raising=False)
    monkeypatch.setattr(core, "GOOGLE_CLIENT_ID", "", raising=False)
    monkeypatch.setattr(core, "E2E_KEY", None, raising=False)
    # A scan exists by default; the 404 test overrides this back to None.
    monkeypatch.setattr(isolated_store, "get_scan", lambda *a, **k: {"id": "s1"})
    return TestClient(app), isolated_store


def test_route_404_when_scan_missing(client, monkeypatch):
    c, store = client
    monkeypatch.setattr(store, "get_scan", lambda *a, **k: None)
    r = c.get("/scans/nope/trace/file/doc-x.docx/data")
    assert r.status_code == 404 and r.json()["detail"] == "scan not found"


def test_route_not_configured(client, monkeypatch):
    c, _ = client
    monkeypatch.setattr(lf, "enabled", lambda: False)
    r = c.get("/scans/s1/trace/file/doc-x.docx/data")
    assert r.status_code == 200 and r.json() == {"status": "not_configured"}


def test_route_ok_wraps_normalized_trace(client, monkeypatch):
    c, _ = client
    monkeypatch.setattr(lf, "enabled", lambda: True)
    seen = {}

    def _fake(tid):
        seen["tid"] = tid
        return {"id": tid, "document": "doc-x.docx", "format": "docx",
                "result": {"score": 90}, "observations": []}

    monkeypatch.setattr(lf, "fetch_trace", _fake)
    r = c.get("/scans/s1/trace/file/doc-x.docx/data")
    body = r.json()
    assert r.status_code == 200 and body["status"] == "ok"
    # the route builds the file-centric trace id from scan + file
    assert seen["tid"] == "s1::doc-x.docx"
    assert body["trace"]["result"]["score"] == 90
