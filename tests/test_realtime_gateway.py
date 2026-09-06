from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import time
from collections import defaultdict
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from api.realtime_events import MAX_REPLAY_EVENTS, RealtimeEvent, owner_scope, stream_key
from realtime_gateway.app import create_app
from realtime_gateway.auth import verify_token
from realtime_gateway.config import Settings
from realtime_gateway.store import RedisEventStore


OWNER = "owner@example.com"
SCOPE = owner_scope(OWNER)
SECRET = "local-shadow-secret-that-is-long-enough"


def event(sequence: int, *, scope: str = SCOPE) -> RealtimeEvent:
    return RealtimeEvent(
        kind="assess.progressed", owner_scope=scope, payload={"completed": sequence},
        occurred_at=datetime(2026, 9, 6, 12, 0, tzinfo=timezone.utc), source_seq=sequence,
        scan_id="scan-1", coalesce_key="scan-1",
    )


def token(owner: str = OWNER, *, secret: str = SECRET, exp: int | None = None) -> str:
    body = json.dumps({"owner_email": owner, "exp": exp or int(time.time()) + 60}, separators=(",", ":")).encode()
    encoded = base64.urlsafe_b64encode(body).rstrip(b"=").decode()
    signature = base64.urlsafe_b64encode(
        hmac.new(secret.encode(), encoded.encode(), hashlib.sha256).digest()
    ).rstrip(b"=").decode()
    return f"{encoded}.{signature}"


class FakeRedis:
    def __init__(self):
        self.streams = defaultdict(list)
        self.closed = False
        self.available = True

    def _check(self):
        if not self.available:
            raise ConnectionError("redis unavailable")

    async def ping(self):
        self._check()

    async def xadd(self, key, fields):
        self._check()
        row_id = f"{len(self.streams[key]) + 1}-0"
        self.streams[key].append((row_id, fields))
        return row_id

    async def xrange(self, key, min="-", max="+", count=None):
        self._check()
        rows = self.streams[key]
        if str(min).startswith("("):
            cursor = tuple(map(int, str(min)[1:].split("-")))
            rows = [row for row in rows if tuple(map(int, row[0].split("-"))) > cursor]
        return list(rows[:count] if count else rows)

    async def xrevrange(self, key, max="+", min="-", count=None):
        rows = list(reversed(self.streams[key]))
        return rows[:count] if count else rows

    async def xread(self, streams, count, block):
        return []

    async def aclose(self):
        self.closed = True


class FiniteStore(RedisEventStore):
    async def listen(self, scope, cursor, *, block_ms):
        if False:
            yield


def settings():
    return Settings(enabled=True, auth_secret=SECRET, block_ms=1)


async def append(redis: FakeRedis, item: RealtimeEvent) -> str:
    return await redis.xadd(
        stream_key(item.owner_scope), {"event": item.to_json(), "event_id": item.event_id}
    )


def test_gateway_is_default_off_and_auth_resolves_private_owner_scope(monkeypatch):
    monkeypatch.delenv("ACP_REALTIME_V1_ENABLED", raising=False)
    with pytest.raises(RuntimeError, match="disabled"):
        create_app(settings=Settings.from_env())
    assert verify_token(token(), SECRET) == OWNER


def test_canonical_publisher_row_round_trips_through_store_and_sse():
    async def scenario():
        redis = FakeRedis()
        store = RedisEventStore(redis)
        first = await append(redis, event(1))
        second = await append(redis, event(2))
        rows = await store.replay(SCOPE, first)
        assert [row_id for row_id, _item in rows] == [second]
        restored = rows[0][1]
        assert restored.stream_id == second
        assert restored.to_sse().startswith(f"id: {second}\nevent: acp-event\ndata: ")
        assert stream_key(SCOPE) == f"acp:realtime:v1:owner:{SCOPE}:events"
    asyncio.run(scenario())


def test_replay_is_bounded_and_rejects_invalid_limits():
    async def scenario():
        redis = FakeRedis()
        store = RedisEventStore(redis)
        for sequence in range(MAX_REPLAY_EVENTS + 2):
            await append(redis, event(sequence))
        assert len(await store.replay(SCOPE, "0-0")) == MAX_REPLAY_EVENTS
        with pytest.raises(ValueError, match="replay limit"):
            await store.replay(SCOPE, "0-0", limit=MAX_REPLAY_EVENTS + 1)
    asyncio.run(scenario())


def test_cursor_status_distinguishes_stale_ahead_and_valid():
    async def scenario():
        redis = FakeRedis()
        store = RedisEventStore(redis)
        redis.streams[stream_key(SCOPE)] = [
            ("10-0", {"event": event(1).to_json()}),
            ("12-0", {"event": event(2).to_json()}),
        ]
        assert await store.cursor_status(SCOPE, "9-0") == "stale"
        assert await store.cursor_status(SCOPE, "11-0") == "valid"
        assert await store.cursor_status(SCOPE, "13-0") == "ahead"
    asyncio.run(scenario())


def test_authenticated_resume_emits_only_canonical_named_frames():
    redis = FakeRedis()
    store = FiniteStore(redis)
    asyncio.run(append(redis, event(1)))
    asyncio.run(append(redis, event(2)))
    with TestClient(create_app(settings=settings(), store=store)) as client:
        response = client.get(
            "/v1/events",
            headers={"Authorization": "Bearer " + token(), "Last-Event-ID": "1-0"},
        )
    assert response.status_code == 200
    assert "id: 2-0\nevent: acp-event" in response.text
    assert '"schema_version":"1.0"' in response.text
    assert '"owner_scope"' in response.text
    assert OWNER not in response.text


@pytest.mark.parametrize("cursor,reason", [("not-a-stream-id", "malformed"), ("99-0", "ahead")])
def test_bad_cursor_requires_reconciliation_without_guessing(cursor, reason):
    redis = FakeRedis()
    store = FiniteStore(redis)
    asyncio.run(append(redis, event(1)))

    async def snapshot(scope):
        return {"scope": scope, "status": "authoritative"}

    with TestClient(create_app(settings=settings(), store=store, snapshot_provider=snapshot)) as client:
        response = client.get(
            "/v1/events",
            headers={"Authorization": "Bearer " + token(), "Last-Event-ID": cursor},
        )
    assert f'event: reconciliation-required\ndata: {{"reason":"{reason}"}}' in response.text
    assert "event: snapshot" in response.text
    assert "event: acp-event" not in response.text


def test_missing_cursor_starts_with_snapshot_not_historical_backfill():
    redis = FakeRedis()
    store = FiniteStore(redis)
    asyncio.run(append(redis, event(1)))

    async def snapshot(scope):
        return {"scope": scope}

    with TestClient(create_app(settings=settings(), store=store, snapshot_provider=snapshot)) as client:
        response = client.get("/v1/events", headers={"Authorization": "Bearer " + token()})
    assert "event: snapshot" in response.text
    assert "event: acp-event" not in response.text


def test_health_reports_redis_outage_and_shutdown_closes_client():
    redis = FakeRedis()
    store = FiniteStore(redis)
    with TestClient(create_app(settings=settings(), store=store)) as client:
        assert client.get("/healthz").status_code == 200
        redis.available = False
        assert client.get("/healthz").status_code == 503
    assert redis.closed
