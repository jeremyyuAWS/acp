"""A severe non-zero scope collapse must not become a successful Discovery baseline."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))


def _run(store, sid, at, *, owner="owner@example.com", kind="drive", account=None,
         files=0, published=False):
    store.init_scan_run(sid, "drive", 0, at, "rb", "h", owner=owner, status="running",
                        scope={"kind": kind,
                               "enumeration": {"complete": True, "truncated": False}})
    if files:
        store.add_inventory(sid, [
            {"file": f"f{i}.pdf", "drive_account_id": account} for i in range(files)
        ])
    if published:
        store.mark_published(sid, at=at)


def test_material_collapse_is_detected(monkeypatch):
    import handlers
    monkeypatch.delenv("ACP_DISCOVERY_COLLAPSE_RATIO", raising=False)
    assert handlers._scope_collapse(37, 6970) == {
        "status": "blocked", "code": "unexpected_scope_collapse",
        "current_count": 37, "baseline_count": 6970,
        "retained_ratio": round(37 / 6970, 6), "threshold_ratio": 0.25,
    }


def test_normal_churn_and_small_estates_are_not_blocked():
    import handlers
    assert handlers._scope_collapse(800, 1000) is None
    assert handlers._scope_collapse(10, 40) is None
    assert handlers._scope_collapse(80, 120) is None


def test_baseline_is_published_whole_source_same_owner_and_account(isolated_store):
    _run(isolated_store, "good", "2026-01-01T00:00:00", files=120, published=True,
         account="alice@example.com")
    _run(isolated_store, "folder", "2026-01-02T00:00:00", kind="folder", files=200,
         published=True, account="alice@example.com")
    _run(isolated_store, "other-account", "2026-01-03T00:00:00", files=300,
         published=True, account="bob@example.com")
    _run(isolated_store, "unpublished", "2026-01-04T00:00:00", files=400,
         account="alice@example.com")
    _run(isolated_store, "now", "2026-01-05T00:00:00")

    baseline = isolated_store.last_published_whole_source_baseline(
        "now", owner="owner@example.com", current_scope={"kind": "drive"},
        drive_account_id="alice@example.com")
    assert baseline["scan_id"] == "good"
    assert baseline["count"] == 120


def test_integrity_fact_survives_in_scan_scope_for_assess_gate(isolated_store):
    _run(isolated_store, "blocked", "2026-01-01T00:00:00")
    isolated_store.merge_scan_scope("blocked", {
        "integrity": {"status": "blocked", "code": "unexpected_scope_collapse",
                      "message": "Reconnect the source"}
    })
    scope = isolated_store.get_scan("blocked", owner="owner@example.com")["run"]["scope"]
    assert scope["integrity"]["status"] == "blocked"


@pytest.fixture()
def client(monkeypatch, isolated_store):
    import core
    from app import app
    from fastapi.testclient import TestClient
    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setattr(core, "ACCESS_CODE", "", raising=False)
    monkeypatch.setattr(core, "GOOGLE_CLIENT_ID", "test-client-id", raising=False)
    monkeypatch.setattr(core, "E2E_KEY", None, raising=False)
    monkeypatch.setattr(core, "verify_gis_token", lambda token: token or None)
    monkeypatch.setattr(core, "email_allowed", lambda email: email == "owner@example.com")
    out = TestClient(app)
    out.headers.update({"Authorization": "Bearer owner@example.com"})
    return out


def test_assess_refuses_a_scope_collapse_even_if_status_is_later_changed(client, isolated_store):
    _run(isolated_store, "blocked-assess", "2026-01-01T00:00:00", files=2)
    isolated_store.merge_scan_scope("blocked-assess", {
        "integrity": {"status": "blocked", "code": "unexpected_scope_collapse",
                      "message": "Reconnect the source"}
    })
    isolated_store.set_scan_status("blocked-assess", "discovered")
    isolated_store.set_setting("assess_params:blocked-assess", "{}")

    response = client.post("/scans/blocked-assess/assess")

    assert response.status_code == 409
    assert response.json()["detail"] == "Reconnect the source"


def test_discovery_fails_before_persisting_a_collapsed_inventory(isolated_store, monkeypatch):
    import core
    import handlers
    import scanner
    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setenv("ACP_DEFER_ANALYSIS_TO_ASSESS", "1")
    monkeypatch.setattr(core, "_interactive_drive_sync_plan", lambda *a, **k: None)
    monkeypatch.setattr(scanner, "_drive_service", lambda token: object())
    _run(isolated_store, "baseline", "2026-01-01T00:00:00", files=120,
         published=True, account="alice@example.com")

    def collapsed_list(*args, **kwargs):
        kwargs["scope_out"].update({"kind": "drive", "raw": 10, "kept": 10,
                                    "truncated": False})
        return [{"name": f"new{i}.pdf", "id": f"id{i}", "mime": "application/pdf",
                 "drive_account_id": "alice@example.com"} for i in range(10)]

    monkeypatch.setattr(scanner, "_list", collapsed_list)
    with pytest.raises(RuntimeError, match="refusing to publish or assess"):
        handlers._scan_discover(
            {"scan_id": "collapsed", "source": "drive", "user": "owner@example.com",
             "drive_token": "token"},
            {"scan_id": "collapsed", "id": "job", "attempts": 1})

    run = isolated_store.get_scan("collapsed", owner="owner@example.com")["run"]
    assert run["status"] == "failed"
    assert run["scope"]["integrity"]["code"] == "unexpected_scope_collapse"
    assert run["scope"]["enumeration"]["complete"] is False
    assert isolated_store.count_inventory("collapsed") == 0
