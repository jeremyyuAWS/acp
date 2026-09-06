"""Every HITL item operation enforces the same owner boundary as the queue list."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

OWNER = "owner@example.org"
OTHER = "other@example.org"


@pytest.fixture()
def st(monkeypatch):
    import core
    import store as store_mod

    monkeypatch.setattr(store_mod, "_SQLITE_PATH", Path(tempfile.mkdtemp()) / "hitl-owner.db")
    value = store_mod.Store()
    monkeypatch.setattr(core, "store", value)
    monkeypatch.setattr(core, "HITL_WEBHOOK", "")
    return value


def _seed(st, owner=OWNER):
    st.init_scan_run("scan-owned", "drive", 1, "t0", "r", "h", owner=owner)
    with st._db.cursor() as cur:
        st._db.execute(cur,
            "INSERT INTO file_records(scan_id,file,engine,status,score,compliant,skipped_rules,remediated_at) "
            "VALUES(%s,%s,'pdf','fail',60,0,0,'2026-09-06T00:00:00Z')",
            ("scan-owned", "private.pdf"))
    st.queue_hitl_deferral("scan-owned", "private.pdf", "review this", 1, rule_id="1.1.1")
    return st.list_hitl_queue(scan_id="scan-owned")[0]


def _client(email):
    from routes import hitl

    app = FastAPI()

    @app.middleware("http")
    async def identity(request: Request, call_next):
        request.state.user_email = email
        return await call_next(request)

    app.include_router(hitl.router)
    return TestClient(app)


@pytest.mark.parametrize("method,path,kwargs", [
    ("put", "/hitl/queue/{item}", {"json": {"status": "approved"}}),
    ("patch", "/hitl/queue/{item}/assign", {"json": {"assignee": OTHER}}),
    ("get", "/hitl/queue/{item}/companion", {}),
])
def test_foreign_user_cannot_operate_on_item(st, method, path, kwargs):
    item = _seed(st)
    response = getattr(_client(OTHER), method)(path.format(item=item["id"]), **kwargs)
    assert response.status_code == 404
    current = st.get_hitl_item(item["id"])
    assert current["status"] == "pending"
    assert current["assignee"] is None


@pytest.mark.parametrize("path", [
    "/hitl/queue/scan-owned/auto",
    "/hitl/queue/scan-owned/verify?file=private.pdf",
])
def test_foreign_user_cannot_queue_work_for_scan(st, path):
    _seed(st)
    response = _client(OTHER).post(path)
    assert response.status_code == 404


def test_owner_can_assign_and_decide_item(st):
    item = _seed(st)
    client = _client(OWNER)
    assigned = client.patch(f"/hitl/queue/{item['id']}/assign", json={"assignee": OWNER})
    assert assigned.status_code == 200
    decided = client.put(f"/hitl/queue/{item['id']}", json={"status": "skipped"})
    assert decided.status_code == 200
    assert decided.json()["status"] == "skipped"
