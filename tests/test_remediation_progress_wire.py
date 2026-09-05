"""The remediation progress contract as a CLIENT sees it — ADR 0052.

`test_remediation_progress_events.py` covers the decisions (what counts as progress, what
retention deletes, what suppression withholds). This file covers what actually goes on the wire,
because every one of those decisions is only worth what the bytes say.

Two properties get asserted against the raw body rather than a parsed field, deliberately:

  * NO DUPLICATION ACROSS A RECONNECT. The client acknowledges by sending back the last `id:` it
    rendered, so the property is that two connections PARTITION the log — everything once, in
    order, with the boundary neither replayed nor skipped. A parsed-field assertion on one
    connection cannot see that.
  * NO SUPPRESSED NAME. A disclosure cannot be taken back, so the check is that the string is not
    in the response at all, not that one key was blanked.
"""
from __future__ import annotations
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

OWNER = "owner@example.com"
OTHER = "stranger@example.com"


def _ago(**kw) -> str:
    return (datetime.now(timezone.utc) - timedelta(**kw)).isoformat()


@pytest.fixture()
def gated_client(monkeypatch, isolated_store):
    import core
    from fastapi.testclient import TestClient
    from app import app

    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setattr(core, "ACCESS_CODE", "", raising=False)
    monkeypatch.setattr(core, "GOOGLE_CLIENT_ID", "test-client-id", raising=False)
    monkeypatch.setattr(core, "E2E_KEY", None, raising=False)
    monkeypatch.setattr(core, "OWNER_EMAIL", OWNER, raising=False)
    monkeypatch.setattr(core, "verify_gis_token", lambda tok: tok or None)
    monkeypatch.setattr(core, "email_allowed", lambda e: True)
    client = TestClient(app)

    def as_user(email):
        client.headers.update({"Authorization": f"Bearer {email}"})
        return client
    return as_user


def _frames(text: str) -> list[dict]:
    """An SSE body as {event, id, data} dicts — the server's half of what the browser's
    `parseSSEFrames` does, so both ends can be asserted against one shape."""
    out = []
    for block in text.split("\n\n"):
        if not block.strip() or block.startswith(":"):
            continue
        frame = {"event": "message", "id": None, "data": None}
        for line in block.split("\n"):
            if line.startswith("event:"):
                frame["event"] = line[6:].strip()
            elif line.startswith("id:"):
                frame["id"] = line[3:].strip()
            elif line.startswith("data:"):
                frame["data"] = line[5:].strip()
        if frame["data"] is not None:
            out.append(frame)
    return out


def _drain(client, sid, headers=None, stop_after=6) -> str:
    with client.stream("GET", f"/scans/{sid}/remediation/stream", headers=headers or {}) as r:
        assert r.status_code == 200
        body = ""
        for chunk in r.iter_text():
            body += chunk
            if "event: done" in body or body.count("\n\n") > stop_after:
                break
    return body


def _events(body: str) -> list[dict]:
    return [f for f in _frames(body) if f["event"] == "remediation-event"]


# ── reconnect ────────────────────────────────────────────────────────────────

def test_a_reconnect_resumes_after_the_last_acknowledged_event_without_duplication(
        gated_client, isolated_store):
    sid, _ = isolated_store.enqueue_scan("s-wire-resume", "local", OWNER, "scan_discover", {})
    for i in range(5):
        isolated_store.append_scan_event(sid, "remediate.fix_applied", owner_email=OWNER,
                                         document=f"{i}.docx", correlation_id="batch-1")

    first = [f["id"] for f in _events(_drain(gated_client(OWNER), sid, {"Last-Event-ID": "0"}))]
    assert first == ["1", "2", "3", "4", "5"]

    # Two more events land while this browser is disconnected.
    for i in range(5, 7):
        isolated_store.append_scan_event(sid, "remediate.verified", owner_email=OWNER,
                                         document=f"{i}.docx", correlation_id="batch-1")

    second = [f["id"] for f in _events(
        _drain(gated_client(OWNER), sid, {"Last-Event-ID": first[-1]}))]
    assert second == ["6", "7"]
    assert not set(first) & set(second), "an event was delivered twice across the reconnect"
    assert first + second == [str(n) for n in range(1, 8)]


def test_an_expired_cursor_forces_a_snapshot_before_any_later_event(gated_client,
                                                                    isolated_store):
    """Expired means REALLY expired — retention deleted the rows, rather than a DELETE written by
    the test to imitate one. That is the difference between exercising the branch and exercising
    a fixture's idea of it."""
    sid, _ = isolated_store.enqueue_scan("s-wire-expired", "local", OWNER, "scan_discover", {})
    for _ in range(20):
        isolated_store.append_scan_event(sid, "remediate.fix_applied", owner_email=OWNER,
                                         document="A.pdf", occurred_at=_ago(days=2))
    for _ in range(3):
        isolated_store.append_scan_event(sid, "remediate.verified", owner_email=OWNER,
                                         document="A.pdf")
    assert isolated_store.prune_scan_events(sid, max_age_hours=24, max_events=8) > 0

    frames = _frames(_drain(gated_client(OWNER), sid, {"Last-Event-ID": "4"}))
    assert frames[0]["event"] == "reconciliation-required", frames[:2]
    assert "events_pruned" in frames[0]["data"]
    # Nothing later may be rendered before the client has re-fetched a snapshot (PRD §17.6).
    assert not _events(_drain(gated_client(OWNER), sid, {"Last-Event-ID": "4"}))


def test_an_unknown_cursor_forces_reconciliation_too(gated_client, isolated_store):
    sid, _ = isolated_store.enqueue_scan("s-wire-unknown", "local", OWNER, "scan_discover", {})
    isolated_store.append_scan_event(sid, "remediate.accepted", owner_email=OWNER)
    for cursor, reason in (("900", "cursor_ahead_of_log"), ("not-a-number", "malformed_cursor")):
        body = _drain(gated_client(OWNER), sid, {"Last-Event-ID": cursor})
        frames = _frames(body)
        assert frames[0]["event"] == "reconciliation-required", (cursor, body[:200])
        assert reason in frames[0]["data"], cursor
        assert not _events(body), cursor


def test_replayed_frames_carry_the_structured_fields_and_a_document_ref(gated_client,
                                                                        isolated_store):
    sid, _ = isolated_store.enqueue_scan("s-wire-shape", "local", OWNER, "scan_discover", {})
    isolated_store.append_scan_event(sid, "remediate.fix_applied", owner_email=OWNER,
                                     document="A.pdf", correlation_id="batch-1",
                                     phase="applying", attempt=1, detail={"fixes": 2})

    (frame,) = _events(_drain(gated_client(OWNER), sid, {"Last-Event-ID": "0"}))
    payload = json.loads(frame["data"])
    assert payload["document"] == "A.pdf"
    assert payload["correlation_id"] == "batch-1"
    assert payload["attempt"] == 1 and payload["phase"] == "applying"
    assert payload["material"] is True
    assert payload["document_ref"]
    assert payload["occurred_at"] and payload["event_id"]
    # The FRAME's id is the cursor, and it must agree with the row it describes — the client
    # persists the frame id, so a disagreement here resumes from a position it never rendered.
    assert frame["id"] == str(payload["seq"])


def test_parallel_documents_arrive_interleaved_but_separable(gated_client, isolated_store):
    """PRD §6D over the wire: one ordered log, three documents, each one's history recoverable by
    its own ref without the client having to trust arrival order."""
    sid, _ = isolated_store.enqueue_scan("s-wire-par", "local", OWNER, "scan_discover", {})
    for document, kind in (("A.pdf", "remediate.fix_applied"),
                           ("B.docx", "remediate.fix_applied"),
                           ("A.pdf", "remediate.verified"),
                           ("B.docx", "remediate.verification_failed"),
                           ("A.pdf", "remediate.delivered")):
        isolated_store.append_scan_event(sid, kind, owner_email=OWNER, document=document,
                                         correlation_id="batch-1")

    payloads = [json.loads(f["data"])
                for f in _events(_drain(gated_client(OWNER), sid, {"Last-Event-ID": "0"},
                                        stop_after=10))]
    by_ref: dict[str, list[str]] = {}
    for payload in payloads:
        by_ref.setdefault(payload["document_ref"], []).append(payload["kind"])
    assert len(by_ref) == 2
    assert sorted(by_ref.values(), key=len) == [
        ["remediate.fix_applied", "remediate.verification_failed"],
        ["remediate.fix_applied", "remediate.verified", "remediate.delivered"],
    ]


# ── privacy ──────────────────────────────────────────────────────────────────

def test_the_stream_never_sends_a_name_the_policy_suppresses(gated_client, isolated_store):
    sid, _ = isolated_store.enqueue_scan("s-wire-priv", "local", OWNER, "scan_discover", {})
    isolated_store.set_setting(isolated_store.FILENAME_PRIVACY_SETTING, "suppressed")
    isolated_store.append_scan_event(sid, "remediate.fix_applied", owner_email=OWNER,
                                     document="Patient 4021 MRI.pdf", detail={"fixes": 1})

    body = _drain(gated_client(OWNER), sid, {"Last-Event-ID": "0"})
    assert "Patient 4021 MRI.pdf" not in body
    (frame,) = _events(body)
    payload = json.loads(frame["data"])
    assert payload["document"] is None and payload["document_suppressed"] is True
    assert payload["document_ref"]              # identity survives; the name does not


def test_the_stream_does_send_the_name_under_the_default_policy(gated_client, isolated_store):
    """The bite check on the test above: a stream that sent no names at all would pass it."""
    sid, _ = isolated_store.enqueue_scan("s-wire-visible", "local", OWNER, "scan_discover", {})
    isolated_store.append_scan_event(sid, "remediate.fix_applied", owner_email=OWNER,
                                     document="Patient 4021 MRI.pdf")
    assert "Patient 4021 MRI.pdf" in _drain(gated_client(OWNER), sid, {"Last-Event-ID": "0"})


# ── the polling fallback ─────────────────────────────────────────────────────

def test_the_polling_fallback_still_serves_the_same_events(gated_client, isolated_store):
    """The stream is the default and the poll is the fallback, so the poll is the path nobody
    watches — and the one a client lands on precisely when the stream is unavailable."""
    sid, _ = isolated_store.enqueue_scan("s-wire-poll", "local", OWNER, "scan_discover", {})
    for i in range(4):
        isolated_store.append_scan_event(sid, "remediate.fix_applied", owner_email=OWNER,
                                         document=f"{i}.docx", correlation_id="batch-1")

    body = gated_client(OWNER).get(f"/scans/{sid}/history").json()
    assert body["available"] is True and body["count"] == 4
    assert [e["seq"] for e in body["events"]] == [1, 2, 3, 4]
    assert body["latest_seq"] == 4
    assert body["events"][0]["document"] == "0.docx"
    assert body["events"][0]["document_ref"]

    after = gated_client(OWNER).get(f"/scans/{sid}/history", params={"after_seq": 2}).json()
    assert [e["seq"] for e in after["events"]] == [3, 4]


def test_the_polling_fallback_honours_suppression_as_well(gated_client, isolated_store):
    sid, _ = isolated_store.enqueue_scan("s-wire-poll-priv", "local", OWNER, "scan_discover", {})
    isolated_store.set_setting(isolated_store.FILENAME_PRIVACY_SETTING, "suppressed")
    isolated_store.append_scan_event(sid, "remediate.fix_applied", owner_email=OWNER,
                                     document="Payroll 2026.xlsx")
    response = gated_client(OWNER).get(f"/scans/{sid}/history")
    assert "Payroll 2026.xlsx" not in response.text
    assert response.json()["events"][0]["document_suppressed"] is True


def test_the_legacy_status_endpoint_is_untouched(gated_client, isolated_store):
    """The shipped progress bar reads this, and none of ADR 0052 is allowed to move it."""
    sid, _ = isolated_store.enqueue_scan("s-wire-legacy", "local", OWNER, "scan_discover", {})
    body = gated_client(OWNER).get(f"/scans/{sid}/remediation-status").json()
    for key in ("queued", "running", "in_flight"):
        assert key in body, key


# ── authorization ────────────────────────────────────────────────────────────

def test_authorization_remains_owner_scoped_on_every_path(gated_client, isolated_store):
    sid, _ = isolated_store.enqueue_scan("s-wire-authz", "local", OWNER, "scan_discover", {})
    isolated_store.append_scan_event(sid, "remediate.fix_applied", owner_email=OWNER,
                                     document="A.pdf")
    stranger = gated_client(OTHER)
    assert stranger.get(f"/scans/{sid}/remediation/stream",
                        headers={"Last-Event-ID": "1"}).status_code == 404
    assert stranger.get(f"/scans/{sid}/history").json()["available"] is False
    assert stranger.get(f"/scans/{sid}/remediation/snapshot").status_code == 404
