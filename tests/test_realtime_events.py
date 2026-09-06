from datetime import datetime, timezone
import json
from uuid import UUID

import pytest

from api.realtime_events import (
    KIND_SPECS,
    MAX_REPLAY_EVENTS,
    MEDIA_TYPE,
    RETENTION_MIN_EVENTS,
    RETENTION_SECONDS,
    Priority,
    RealtimeEvent,
    coalescing_bucket,
    legacy_sse_data,
    owner_scope,
    parse_last_event_id,
    stream_key,
)


NOW = datetime(2026, 9, 6, 12, 30, 45, 123000, tzinfo=timezone.utc)
SCOPE = owner_scope("Owner@Example.COM ")


def event(kind="assess.progressed", **overrides):
    values = dict(kind=kind, owner_scope=SCOPE, payload={"completed": 3}, occurred_at=NOW)
    values.update(overrides)
    return RealtimeEvent(**values)


def test_contract_constants_pin_transport_and_retention():
    assert MEDIA_TYPE.endswith("version=1.0")
    assert RETENTION_SECONDS == 86_400
    assert RETENTION_MIN_EVENTS == 10_000
    assert MAX_REPLAY_EVENTS == 500


def test_owner_scope_is_normalized_private_and_keys_are_tenant_scoped():
    assert SCOPE == owner_scope("owner@example.com")
    assert "owner@example.com" not in stream_key(SCOPE)
    assert stream_key(SCOPE) == f"acp:realtime:v1:owner:{SCOPE}:events"


def test_serialization_is_stable_json_with_utc_instants_and_derived_priority():
    item = event(event_id="00000000-0000-4000-8000-000000000001", stream_id="1725638400123-4",
                 stale_after_ms=30_000, source_seq=7, scan_id="scan-1")
    body = json.loads(item.to_json())
    assert body == {
        "schema_version": "1.0", "event_id": "00000000-0000-4000-8000-000000000001",
        "stream_id": "1725638400123-4", "kind": "assess.progressed", "priority": 3,
        "owner_scope": SCOPE, "occurred_at": "2026-09-06T12:30:45.123Z",
        "observed_at": body["observed_at"], "stale_after_ms": 30_000, "source_seq": 7,
        "scan_id": "scan-1", "payload": {"completed": 3},
    }
    UUID(body["event_id"])


def test_sse_uses_redis_id_as_last_event_id_cursor():
    item = event(stream_id="1725638400123-4")
    frame = item.to_sse()
    assert frame.startswith("id: 1725638400123-4\nevent: acp-event\ndata: {")
    assert frame.endswith("\n\n")
    assert parse_last_event_id("1725638400123-4") == (1725638400123, 4)
    assert parse_last_event_id(None) is None


def test_round_trip_accepts_additive_minor_fields_but_refuses_a_new_major():
    source = event(stream_id="1725638400123-4").to_dict()
    source.update(schema_version="1.7", future_optional_field=True)
    restored = RealtimeEvent.from_dict(source)
    assert restored.to_dict()["event_id"] == source["event_id"]
    source["schema_version"] = "2.0"
    with pytest.raises(ValueError, match="unsupported"):
        RealtimeEvent.from_dict(source)


@pytest.mark.parametrize("bad", ["$", "1", "1-a", "-1-0", "01-0", "1-01", " 1-0"])
def test_invalid_last_event_id_requires_reconciliation_instead_of_guessing(bad):
    with pytest.raises(ValueError, match="Redis Stream ID"):
        parse_last_event_id(bad)


def test_closed_kind_vocabulary_covers_every_required_source():
    prefixes = {kind.split(".", 1)[0] for kind in KIND_SPECS}
    assert {"discover", "assess", "remediate", "queue", "worker", "capacity", "alert"} <= prefixes
    with pytest.raises(ValueError, match="unknown realtime event kind"):
        event("assess.typoed")


def test_contract_rejects_naive_time_bad_priority_and_non_json_payload():
    with pytest.raises(ValueError, match="timezone-aware"):
        event(occurred_at=datetime(2026, 9, 6))
    with pytest.raises(ValueError, match="priority"):
        event(priority=Priority.CRITICAL)
    with pytest.raises(ValueError, match="finite JSON"):
        event(payload={"bad": float("nan")})


def test_coalescing_never_drops_critical_or_terminal_events():
    assert coalescing_bucket(event(coalesce_key="scan-1")) == ("assess.progressed", "scan-1")
    assert coalescing_bucket(event("capacity.shortage_detected", coalesce_key="westus")) is None
    assert coalescing_bucket(event("assess.completed", coalesce_key="scan-1")) is None
    assert coalescing_bucket(event()) is None


def test_legacy_snapshot_serialization_stays_an_untyped_message_frame():
    payload = {"status": "running", "done": 3}
    assert legacy_sse_data(payload) == 'data: {"status":"running","done":3}\n\n'
    assert "event:" not in legacy_sse_data(payload)
