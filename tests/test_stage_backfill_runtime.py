from datetime import datetime, timedelta, timezone

import core


def test_maintenance_lease_is_singleton_and_recoverable(isolated_store):
    now = datetime(2026, 9, 7, tzinfo=timezone.utc)
    assert isolated_store.claim_maintenance_lease(
        "stage-execution-backfill-v1", lease_seconds=60, now=now.isoformat()) is True
    assert isolated_store.claim_maintenance_lease(
        "stage-execution-backfill-v1", lease_seconds=60, now=(now + timedelta(seconds=30)).isoformat()) is False
    assert isolated_store.claim_maintenance_lease(
        "stage-execution-backfill-v1", lease_seconds=60, now=(now + timedelta(seconds=61)).isoformat()) is True


def test_runtime_backfill_runs_once_and_persists_a_report(monkeypatch):
    class Store:
        marker = None
        claims = 0
        backfills = 0

        def get_setting(self, key): return self.marker
        def claim_maintenance_lease(self, name, lease_seconds):
            self.claims += 1
            return True
        def backfill_stage_executions(self):
            self.backfills += 1
            return {"batches_seen": 4, "executions_created": 3, "work_items_created": 9,
                    "provenance": "inferred"}
        def set_setting(self, key, value): self.marker = value

    store = Store()
    monkeypatch.setattr(core, "get_store", lambda: store)
    first = core._run_stage_execution_backfill_once()
    second = core._run_stage_execution_backfill_once()
    assert first["executions_created"] == 3
    assert second is None
    assert store.claims == store.backfills == 1
    assert '"provenance": "inferred"' in store.marker


def test_interrupted_backfill_does_not_write_completion_marker(monkeypatch):
    class Store:
        marker = None
        def get_setting(self, key): return self.marker
        def claim_maintenance_lease(self, name, lease_seconds): return True
        def backfill_stage_executions(self): raise RuntimeError("worker replaced")
        def set_setting(self, key, value): self.marker = value

    store = Store()
    monkeypatch.setattr(core, "get_store", lambda: store)
    try:
        core._run_stage_execution_backfill_once()
    except RuntimeError as exc:
        assert str(exc) == "worker replaced"
    else:
        raise AssertionError("interrupted migration must surface to the retrying sweep loop")
    assert store.marker is None
