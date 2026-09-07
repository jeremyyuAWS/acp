from __future__ import annotations

import json
import sys
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))

import capacity_reconcile as reconcile  # noqa: E402
import capacity_schedule as cs  # noqa: E402
import capacity_store as store_mod  # noqa: E402


class Store:
    def __init__(self):
        self.settings, self.decisions = {}, []
    def get_setting(self, key, default=None):
        return self.settings.get(key, default)
    def set_setting(self, key, value):
        self.settings[key] = value
    def log_decision(self, actor, action, **kw):
        self.decisions.append({"actor": actor, "action": action, **kw})


class Gateway:
    def __init__(self):
        self.scales, self.applied = {}, []
    def read_scale(self, app):
        # Preserve exactly the rules the desired policy carries so preflight permits the write.
        return self.scales.get(app)
    def apply_scale(self, policy):
        self.applied.append(policy)
        self.scales[policy.app] = {"min_replicas": policy.min_replicas,
                                   "max_replicas": policy.max_replicas,
                                   "rules": [r.as_dict() for r in policy.rules]}


def utc(hour, minute=0):
    return datetime(2026, 9, 7, hour, minute, tzinfo=timezone.utc)


def applied_store():
    store = Store()
    schedule = replace(cs.PROPOSED, enabled=True, version=3, applied=False)
    store.settings[store_mod.SCHEDULE_KEY] = store_mod._serialise(schedule)
    store.settings[store_mod.APPLICATION_KEY] = json.dumps(
        {"state": "applied", "desired_version": 3, "applied_version": 3, "apps": []})
    return store, schedule


def seeded_gateway(schedule):
    gateway = Gateway()
    policies = __import__("capacity_policy").policy_for(schedule, __import__("queue_scaler").lane_job_types())
    for policy in policies:
        gateway.scales[policy.app] = {"min_replicas": policy.min_replicas,
                                     "max_replicas": policy.max_replicas,
                                     "rules": [r.as_dict() for r in policy.rules]}
    return gateway


def test_override_is_applied_and_cron_cannot_outrank_it():
    store, schedule = applied_store()
    now = utc(15)
    override = store_mod.set_override(store, mode="custom", floors={"assess": 2}, duration="1h",
                                      reason="test run", actor="a", schedule=schedule, now=now)
    gateway = seeded_gateway(schedule)
    result = reconcile.CapacityReconciler(store, gateway, clock=lambda: now).reconcile_once()
    assess = next(p for p in gateway.applied if p.service == "assess")
    assert assess.min_replicas == 2
    cron = next(rule for rule in assess.rules if rule.name == "business-hours")
    assert cron.metadata["desiredReplicas"] == "2"
    assert result["state"] == "applied"
    assert override["correlation_id"] in result["desired_key"]


def test_expiry_restores_the_saved_schedule_policy():
    store, schedule = applied_store()
    now = [utc(15)]
    store_mod.set_override(store, mode="custom", floors={"assess": 2}, duration="30m",
                           reason="test", actor="a", schedule=schedule, now=now[0])
    gateway = seeded_gateway(schedule)
    worker = reconcile.CapacityReconciler(store, gateway, clock=lambda: now[0])
    worker.reconcile_once()
    gateway.applied.clear()
    now[0] += timedelta(minutes=31)
    result = worker.reconcile_once()
    assess = next(p for p in gateway.applied if p.service == "assess")
    assert assess.min_replicas == schedule.off_hours["assess"]
    assert any(rule.name == "business-hours" for rule in assess.rules)
    assert result["desired_key"] == "schedule:3"
    assert any(d["action"] == "settings.capacity_schedule.restored" for d in store.decisions)


def test_cancel_restores_on_the_next_reconciliation():
    store, schedule = applied_store()
    now = utc(15)
    store_mod.set_override(store, mode="off_hours", floors=None, duration="1h", reason="test",
                           actor="a", schedule=schedule, now=now)
    gateway = seeded_gateway(schedule)
    worker = reconcile.CapacityReconciler(store, gateway, clock=lambda: now)
    worker.reconcile_once()
    store_mod.clear_override(store, actor="a")
    gateway.applied.clear()
    assert worker.reconcile_once()["desired_key"] == "schedule:3"
    assert gateway.applied


def test_gateway_absence_and_unapplied_intent_fail_closed():
    store, schedule = applied_store()
    assert reconcile.CapacityReconciler(store, None).reconcile_once()["state"] == "disabled"
    store.settings[store_mod.APPLICATION_KEY] = json.dumps({"applied_version": 2})
    gateway = seeded_gateway(schedule)
    result = reconcile.CapacityReconciler(store, gateway).reconcile_once()
    assert result["state"] == "ineligible"
    assert gateway.applied == []


def test_startup_adopts_the_explicitly_applied_version_without_a_duplicate_write():
    store, schedule = applied_store()
    gateway = seeded_gateway(schedule)
    result = reconcile.CapacityReconciler(store, gateway, clock=lambda: utc(15)).reconcile_once()
    assert result["applied_key"] == "schedule:3"
    assert gateway.applied == []


def test_holiday_uses_off_hours_for_the_full_local_day_then_restores():
    store, schedule = applied_store()
    schedule = replace(schedule, holidays=("2026-09-07",))
    store.settings[store_mod.SCHEDULE_KEY] = store_mod._serialise(schedule)
    now = [utc(15)]  # 08:00 on the holiday in America/Los_Angeles.
    gateway = seeded_gateway(schedule)
    worker = reconcile.CapacityReconciler(store, gateway, clock=lambda: now[0])

    holiday = worker.reconcile_once()
    assess = next(p for p in gateway.applied if p.service == "assess")
    assert assess.min_replicas == schedule.off_hours["assess"]
    assert holiday["desired_key"] == "holiday:3:2026-09-07"
    assert holiday["authority"] == "holiday_exception"

    gateway.applied.clear()
    now[0] += timedelta(days=1)
    restored = worker.reconcile_once()
    assert restored["desired_key"] == "schedule:3"
    assert gateway.applied


def test_only_one_replica_claims_a_desired_policy():
    store, schedule = applied_store()
    now = utc(15)
    store_mod.set_override(store, mode="off_hours", floors=None, duration="1h", reason="test",
                           actor="a", schedule=schedule, now=now)
    store.claim_maintenance_lease = lambda *args, **kwargs: False
    gateway = seeded_gateway(schedule)
    result = reconcile.CapacityReconciler(store, gateway, clock=lambda: now).reconcile_once()
    assert result["state"] == "leader_busy"
    assert gateway.applied == []


def test_failure_is_persisted_audited_and_backed_off():
    store, schedule = applied_store()
    now = utc(15)
    store_mod.set_override(store, mode="off_hours", floors=None, duration="1h", reason="test",
                           actor="a", schedule=schedule, now=now)
    gateway = seeded_gateway(schedule)
    gateway.apply_scale = lambda _policy: (_ for _ in ()).throw(RuntimeError("Azure failed"))
    worker = reconcile.CapacityReconciler(store, gateway, clock=lambda: now)
    failed = worker.reconcile_once()
    assert failed["state"] == "partial"
    assert failed["failures"] == 1 and failed["next_attempt_at"]
    assert worker.reconcile_once()["state"] == "backoff"
    assert any(d["action"] == "settings.capacity_reconcile.failed" for d in store.decisions)


def test_schedule_change_during_apply_never_certifies_stale_policy():
    store, schedule = applied_store()
    now = utc(15)
    store_mod.set_override(store, mode="off_hours", floors=None, duration="1h", reason="test",
                           actor="a", schedule=schedule, now=now)
    gateway = seeded_gateway(schedule)
    original_apply = gateway.apply_scale
    moved = False

    def apply_and_move(policy):
        nonlocal moved
        original_apply(policy)
        if not moved:
            moved = True
            newer = replace(schedule, version=4)
            store.settings[store_mod.SCHEDULE_KEY] = store_mod._serialise(newer)
            store.settings[store_mod.APPLICATION_KEY] = json.dumps(
                {"state": "applied", "desired_version": 4, "applied_version": 4, "apps": []})

    gateway.apply_scale = apply_and_move
    result = reconcile.CapacityReconciler(store, gateway, clock=lambda: now).reconcile_once()
    assert result["state"] != "applied"
    assert result["applied_key"] is None
    assert result["failures"] == 1
