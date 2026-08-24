"""Persistent reviewer assignment for HITL queue items.

assign_hitl_item() writes to the DB; list_hitl_queue() returns the value;
a second call with None clears it; the PATCH /hitl/queue/{id}/assign endpoint
is the HTTP surface for the same operation.
"""
from __future__ import annotations
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))


@pytest.fixture()
def st(monkeypatch):
    import store as store_mod
    monkeypatch.setattr(store_mod, "_SQLITE_PATH", Path(tempfile.mkdtemp()) / "assign.db")
    return store_mod.Store()


def _item(st, sid="s1", f="doc.pdf", rule="1.1.1"):
    st.init_scan_run(sid, "drive", 1, "t0", "r", "h")
    with st._db.cursor() as cur:
        st._db.execute(cur,
            "INSERT INTO file_records(scan_id,file,engine,status,score,compliant,skipped_rules,remediated_at) "
            "VALUES(%s,%s,'pdf','fail',60,0,0,'2026-08-01T00:00:00')", (sid, f))
    st.queue_hitl_deferral(sid, f, "alt text needed", 1, rule_id=rule)
    return next(i for i in st.list_hitl_queue(scan_id=sid))


def test_assign_persists(st):
    item = _item(st)
    result = st.assign_hitl_item(item["id"], "alice@example.com")
    assert result["assignee"] == "alice@example.com"


def test_assign_visible_in_list(st):
    item = _item(st)
    st.assign_hitl_item(item["id"], "bob@example.com")
    rows = st.list_hitl_queue(scan_id="s1")
    assert rows[0]["assignee"] == "bob@example.com"


def test_assign_clear(st):
    item = _item(st)
    st.assign_hitl_item(item["id"], "carol@example.com")
    st.assign_hitl_item(item["id"], None)
    row = st.get_hitl_item(item["id"])
    assert row["assignee"] is None


def test_assign_does_not_change_status(st):
    item = _item(st)
    st.assign_hitl_item(item["id"], "dave@example.com")
    row = st.get_hitl_item(item["id"])
    assert row["status"] == "pending"


def test_patch_endpoint(st, monkeypatch):
    import core as core_mod
    monkeypatch.setattr(core_mod, "store", st)

    from fastapi.testclient import TestClient
    from fastapi import FastAPI
    from routes import hitl as hitl_routes

    app = FastAPI()
    app.include_router(hitl_routes.router)
    client = TestClient(app)

    item = _item(st)
    resp = client.patch(f"/hitl/queue/{item['id']}/assign",
                        json={"assignee": "eve@example.com"})
    assert resp.status_code == 200
    assert resp.json()["assignee"] == "eve@example.com"


def test_patch_endpoint_clear(st, monkeypatch):
    import core as core_mod
    monkeypatch.setattr(core_mod, "store", st)

    from fastapi.testclient import TestClient
    from fastapi import FastAPI
    from routes import hitl as hitl_routes

    app = FastAPI()
    app.include_router(hitl_routes.router)
    client = TestClient(app)

    item = _item(st)
    client.patch(f"/hitl/queue/{item['id']}/assign", json={"assignee": "frank@example.com"})
    resp = client.patch(f"/hitl/queue/{item['id']}/assign", json={"assignee": None})
    assert resp.status_code == 200
    assert resp.json()["assignee"] is None


def test_patch_endpoint_404(st, monkeypatch):
    import core as core_mod
    monkeypatch.setattr(core_mod, "store", st)

    from fastapi.testclient import TestClient
    from fastapi import FastAPI
    from routes import hitl as hitl_routes

    app = FastAPI()
    app.include_router(hitl_routes.router)
    client = TestClient(app)

    resp = client.patch("/hitl/queue/nonexistent/assign", json={"assignee": "x@example.com"})
    assert resp.status_code == 404
