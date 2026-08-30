"""content_workspace_retention.py (ADR 0044, PRD §28) — the baseline retention sweep.

Same testing shape as tests/test_reconciliation_sweeper.py: a pure, store-injected function,
exercised directly against isolated_store rather than through any route (there is no
user-facing route for this — it's a maintenance sweep, like sweeper.run_sweep()).
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

import content_workspace_retention as retention

OWNER = "alice@x.com"
PAST = "2020-01-01T00:00:00+00:00"
FUTURE = "2099-01-01T00:00:00+00:00"


@pytest.fixture()
def ws(isolated_store):
    wid = uuid.uuid4().hex[:12]
    isolated_store.create_content_workspace(wid, owner_email=OWNER, name="Retention test")
    return wid


def _make_version(isolated_store, ws, *, retention_date=None):
    doc_id = uuid.uuid4().hex[:12]
    isolated_store.create_content_workspace_document(doc_id, workspace_id=ws, owner_email=OWNER)
    version_id = uuid.uuid4().hex[:12]
    isolated_store.create_content_workspace_document_version(
        version_id, document_id=doc_id, version_seq=1, content_hash=uuid.uuid4().hex,
        retention_date=retention_date)
    return doc_id, version_id


def test_sweep_is_a_no_op_when_nothing_has_a_retention_date(isolated_store, ws):
    _make_version(isolated_store, ws)
    result = retention.run_content_workspace_retention_sweep(isolated_store)
    assert result == {"versions_expired": 0, "blobs_deleted": 0}


def test_sweep_expires_a_past_due_version(isolated_store, ws, monkeypatch):
    import workspace_blob
    monkeypatch.setattr(workspace_blob, "delete_document_version", lambda *a, **kw: True)
    doc_id, version_id = _make_version(isolated_store, ws, retention_date=PAST)

    result = retention.run_content_workspace_retention_sweep(isolated_store, as_of="2026-01-01T00:00:00+00:00")
    assert result == {"versions_expired": 1, "blobs_deleted": 1}

    [v] = isolated_store.list_content_workspace_document_versions(doc_id)
    assert v["lifecycle_state"] == "expired"


def test_sweep_leaves_a_future_retention_date_alone(isolated_store, ws):
    doc_id, version_id = _make_version(isolated_store, ws, retention_date=FUTURE)
    result = retention.run_content_workspace_retention_sweep(isolated_store, as_of="2026-01-01T00:00:00+00:00")
    assert result == {"versions_expired": 0, "blobs_deleted": 0}

    [v] = isolated_store.list_content_workspace_document_versions(doc_id)
    assert v["lifecycle_state"] != "expired"


def test_sweep_counts_versions_expired_even_when_the_blob_delete_fails(isolated_store, ws, monkeypatch):
    """Blob storage not configured (the default in tests) or the object already gone are both
    non-fatal — the version is still marked expired, since retention here means the bytes stop
    being retrievable, and a missing blob already satisfies that."""
    import workspace_blob
    monkeypatch.setattr(workspace_blob, "delete_document_version", lambda *a, **kw: False)
    doc_id, version_id = _make_version(isolated_store, ws, retention_date=PAST)

    result = retention.run_content_workspace_retention_sweep(isolated_store, as_of="2026-01-01T00:00:00+00:00")
    assert result == {"versions_expired": 1, "blobs_deleted": 0}

    [v] = isolated_store.list_content_workspace_document_versions(doc_id)
    assert v["lifecycle_state"] == "expired"


def test_sweep_is_idempotent_on_a_second_run(isolated_store, ws, monkeypatch):
    import workspace_blob
    calls = []
    monkeypatch.setattr(workspace_blob, "delete_document_version",
                        lambda *a, **kw: calls.append(a) or True)
    _make_version(isolated_store, ws, retention_date=PAST)

    retention.run_content_workspace_retention_sweep(isolated_store, as_of="2026-01-01T00:00:00+00:00")
    result2 = retention.run_content_workspace_retention_sweep(isolated_store, as_of="2026-01-01T00:00:00+00:00")

    assert result2 == {"versions_expired": 0, "blobs_deleted": 0}
    assert len(calls) == 1  # the blob delete was never attempted a second time


def test_sweep_handles_multiple_expired_versions_across_documents(isolated_store, ws, monkeypatch):
    import workspace_blob
    monkeypatch.setattr(workspace_blob, "delete_document_version", lambda *a, **kw: True)
    _make_version(isolated_store, ws, retention_date=PAST)
    _make_version(isolated_store, ws, retention_date=PAST)
    _make_version(isolated_store, ws, retention_date=FUTURE)

    result = retention.run_content_workspace_retention_sweep(isolated_store, as_of="2026-01-01T00:00:00+00:00")
    assert result == {"versions_expired": 2, "blobs_deleted": 2}
