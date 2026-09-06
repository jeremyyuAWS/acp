from __future__ import annotations

from datetime import datetime, timezone

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from api.realtime_events import RealtimeEvent, owner_scope
from api.routes import realtime
from realtime_gateway.store import RedisEventStore


OWNER = "owner@example.com"


class FiniteStore(RedisEventStore):
    def __init__(self, rows=()):
        self.rows = list(rows)
        self.closed = False

    async def cursor_status(self, scope, cursor):
        return "valid"

    async def replay(self, scope, cursor, *, limit):
        assert scope == owner_scope(OWNER)
        return self.rows

    async def listen(self, scope, cursor, *, block_ms):
        if False:
            yield

    async def close(self):
        self.closed = True


def _event(stream_id="2-0"):
    return RealtimeEvent(
        kind="assess.progressed", owner_scope=owner_scope(OWNER), payload={"completed": 2},
        occurred_at=datetime(2026, 9, 6, tzinfo=timezone.utc), stream_id=stream_id,
    )


def _app():
    app = FastAPI()

    @app.middleware("http")
    async def existing_access_gate(request: Request, call_next):
        request.state.user_email = OWNER
        return await call_next(request)

    app.include_router(realtime.router)
    return app


def test_bridge_is_default_off(monkeypatch):
    monkeypatch.delenv("ACP_REALTIME_V1_ENABLED", raising=False)
    assert TestClient(_app()).get("/api/realtime/v1/stream").status_code == 404


def test_status_is_the_owner_scoped_authoritative_twin(monkeypatch):
    monkeypatch.setenv("ACP_REALTIME_V1_ENABLED", "true")
    monkeypatch.setattr(realtime.core.store, "active_scan", lambda *, owner: {"id": "scan-1", "status": "running"})
    monkeypatch.setattr(realtime.core.store, "active_workflows", lambda owner: [{"scan_id": "scan-1"}])
    response = TestClient(_app()).get("/api/realtime/v1/status")
    assert response.status_code == 200
    assert response.json() == {
        "scan_id": "scan-1", "scan_status": "running",
        "active_workflows": [{"scan_id": "scan-1"}],
    }


def test_bridge_uses_gate_identity_and_preserves_redis_cursor(monkeypatch):
    store = FiniteStore([("2-0", _event())])
    monkeypatch.setenv("ACP_REALTIME_V1_ENABLED", "true")
    monkeypatch.setattr(realtime, "_store", lambda: store)
    response = TestClient(_app()).get(
        "/api/realtime/v1/stream", headers={"Last-Event-ID": "1-0"},
    )
    assert response.status_code == 200
    assert response.text.startswith("id: 2-0\nevent: acp-event\ndata: ")
    assert f'"owner_scope":"{owner_scope(OWNER)}"' in response.text
    assert OWNER not in response.text
    assert store.closed


def test_bridge_bad_cursor_requires_authoritative_reconciliation(monkeypatch):
    store = FiniteStore()
    monkeypatch.setenv("ACP_REALTIME_V1_ENABLED", "true")
    monkeypatch.setattr(realtime, "_store", lambda: store)
    response = TestClient(_app()).get(
        "/api/realtime/v1/stream", headers={"Last-Event-ID": "event-uuid-is-not-a-cursor"},
    )
    assert response.status_code == 200
    assert response.text == 'event: reconciliation-required\ndata: {"reason":"malformed"}\n\n'
    assert store.closed
