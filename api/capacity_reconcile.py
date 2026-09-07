"""Durably apply temporary capacity overrides and restore the published schedule.

The schedule's cron policy handles ordinary time transitions without revisions. Overrides are
different: they temporarily replace every warm floor, so this reconciler publishes one bounded,
audited policy on creation and republishes the saved schedule on cancellation or expiry.
"""
from __future__ import annotations

import os
import threading
import time
import uuid
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import capacity_apply
import capacity_policy
import capacity_store
import queue_scaler
from swallowed import swallowed

MIN_INTERVAL_SECONDS = 5
MAX_BACKOFF_SECONDS = 300


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _override_policy(schedule, override: dict):
    """Make an override authoritative now; cron must not silently outrank a lower override."""
    floors = dict(override.get("floors") or {})
    policies = []
    for policy in capacity_policy.policy_for(schedule, queue_scaler.lane_job_types()):
        floor = int(floors.get(policy.service, policy.min_replicas))
        if floor < 0 or floor > policy.max_replicas:
            raise ValueError(f"override floor for {policy.service} is outside its safe range")
        # Keep the managed cron rule's identity so the complete-policy safety check does not
        # mistake it for an unknown rule we are about to delete. While the override lasts its
        # desired replica count is the override floor, making it harmless in either time mode.
        rules = tuple(
            replace(rule, metadata={**rule.metadata, "desiredReplicas": str(floor)})
            if rule.name == "business-hours" else rule
            for rule in policy.rules
        )
        policies.append(replace(policy, min_replicas=floor, rules=rules))
    return policies


def _holiday_date(schedule, now: datetime) -> str | None:
    local_date = now.astimezone(ZoneInfo(schedule.timezone)).date().isoformat()
    return local_date if local_date in set(schedule.holidays or ()) else None


def _holiday_policy(schedule):
    """Hold saved off-hours floors throughout a holiday in the schedule timezone."""
    return _override_policy(schedule, {"floors": dict(schedule.off_hours)})


class CapacityReconciler:
    """One-at-a-time, persisted reconciliation with exponential retry backoff."""

    def __init__(self, store, gateway, *, interval_seconds: float = 15, clock=_now):
        self.store = store
        self.gateway = gateway
        self.interval_seconds = max(MIN_INTERVAL_SECONDS, float(interval_seconds))
        self.clock = clock
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread = None
        self._run_lock = threading.Lock()

    def reconcile_once(self) -> dict:
        if self.gateway is None:
            return {"state": "disabled", "reason": "capacity application is not configured"}
        if not self._run_lock.acquire(blocking=False):
            return {"state": "busy"}
        try:
            return self._reconcile_locked()
        finally:
            self._run_lock.release()

    def _reconcile_locked(self) -> dict:
        now = self.clock()
        schedule = capacity_store.load_schedule(self.store)
        application = capacity_store.load_application(self.store)
        override = capacity_store.get_override(self.store, now)
        state = capacity_store.load_reconciliation(self.store)

        # Saving intent must never silently become an Azure write. Reconcile only a schedule
        # that an administrator has explicitly and successfully applied.
        if application.get("applied_version") != schedule.version:
            return {"state": "ineligible", "reason": "saved schedule is not applied"}

        holiday = None if override else _holiday_date(schedule, now)
        if override:
            desired_key = (f"override:{schedule.version}:"
                           f"{override.get('correlation_id')}:{override.get('expires_at')}")
            authority = "manual_override"
            policies = _override_policy(schedule, override)
            correlation_id = str(override.get("correlation_id") or uuid.uuid4().hex[:12])
        elif holiday:
            desired_key = f"holiday:{schedule.version}:{holiday}"
            authority = "holiday_exception"
            policies = _holiday_policy(schedule)
            correlation_id = uuid.uuid4().hex[:12]
        else:
            desired_key = f"schedule:{schedule.version}"
            authority = "saved_schedule"
            policies = capacity_policy.policy_for(schedule, queue_scaler.lane_job_types())
            correlation_id = uuid.uuid4().hex[:12]

        # The explicit apply route already certified this version. On the first startup, adopt
        # that as the reconciliation baseline instead of needlessly publishing the same policy
        # again. Once an override has been recorded, a return to this key is a real restoration.
        if not override and not holiday and not state.get("desired_key"):
            baseline = {"state": "applied", "desired_key": desired_key,
                        "applied_key": desired_key, "schedule_version": schedule.version,
                        "authority": authority, "attempted_at": now.isoformat(),
                        "completed_at": now.isoformat(), "failures": 0,
                        "next_attempt_at": None, "apps": []}
            return capacity_store.save_reconciliation(
                self.store, baseline, action="settings.capacity_reconcile.baseline",
                reason="adopt last explicitly applied schedule", correlation_id=correlation_id)

        if state.get("applied_key") == desired_key and state.get("state") == "applied":
            return state
        retry_at = state.get("next_attempt_at") if state.get("desired_key") == desired_key else None
        if retry_at:
            try:
                if datetime.fromisoformat(retry_at) > now:
                    return {**state, "state": "backoff"}
            except (TypeError, ValueError):
                pass

        # API replicas share the same settings database. Elect one for this desired state so a
        # scale-out does not publish identical Container App revisions concurrently. Lightweight
        # test stores need no distributed lease; the in-process lock above is enough for them.
        claim = getattr(self.store, "claim_maintenance_lease", None)
        if claim and not claim(f"capacity-reconcile:{desired_key}", lease_seconds=300,
                               now=now.isoformat()):
            return {**state, "state": "leader_busy", "desired_key": desired_key}

        attempted = {"state": "applying", "desired_key": desired_key,
                     "applied_key": state.get("applied_key"),
                     "schedule_version": schedule.version, "authority": authority,
                     "attempted_at": now.isoformat(), "failures": state.get("failures", 0),
                     "apps": []}
        capacity_store.save_reconciliation(
            self.store, attempted, action="settings.capacity_reconcile.started",
            reason="temporary override" if override else "holiday exception" if holiday else "restore saved schedule",
            correlation_id=correlation_id)
        result = capacity_apply.apply_policies(policies, self.gateway)

        # An override can expire or be cancelled while Azure is applying. Never certify that
        # stale intent; the next tick restores the then-current desired policy.
        current_now = self.clock()
        current_override = capacity_store.get_override(self.store, current_now)
        current_holiday = None if current_override else _holiday_date(schedule, current_now)
        current_key = (f"override:{schedule.version}:{current_override.get('correlation_id')}:"
                       f"{current_override.get('expires_at')}") if current_override else (
                           f"holiday:{schedule.version}:{current_holiday}" if current_holiday
                           else f"schedule:{schedule.version}")
        successful = result.get("state") == "applied" and current_key == desired_key
        failures = 0 if successful else int(state.get("failures") or 0) + 1
        delay = min(MAX_BACKOFF_SECONDS, self.interval_seconds * (2 ** min(failures, 5)))
        finished = {**attempted, "state": "applied" if successful else result.get("state", "failed"),
                    "applied_key": desired_key if successful else state.get("applied_key"),
                    "completed_at": self.clock().isoformat(), "failures": failures,
                    "next_attempt_at": None if successful else (self.clock() + timedelta(seconds=delay)).isoformat(),
                    "apps": list(result.get("apps") or [])}
        return capacity_store.save_reconciliation(
            self.store, finished,
            action=("settings.capacity_override.reconciled" if successful and override
                    else "settings.capacity_holiday.reconciled" if successful and holiday
                    else "settings.capacity_schedule.restored" if successful
                    else "settings.capacity_reconcile.failed"),
            reason="temporary override" if override else "holiday exception" if holiday else "restore saved schedule",
            correlation_id=correlation_id)

    def start(self) -> None:
        if self.gateway is None or (self._thread and self._thread.is_alive()):
            return
        self._thread = threading.Thread(target=self._loop, name="capacity-reconciler", daemon=True)
        self._thread.start()

    def wake(self) -> None:
        self._wake.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.reconcile_once()
            except Exception:  # noqa: BLE001 - one failed tick cannot kill restoration
                swallowed("capacity_reconcile: reconciliation tick failed")
            self._wake.wait(self.interval_seconds)
            self._wake.clear()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=min(5, self.interval_seconds))


_instance: CapacityReconciler | None = None


def start(store, gateway) -> CapacityReconciler:
    global _instance
    interval = float(os.environ.get("ACP_CAPACITY_RECONCILE_SECONDS", "15"))
    _instance = CapacityReconciler(store, gateway, interval_seconds=interval)
    _instance.start()
    return _instance


def wake() -> None:
    if _instance:
        _instance.wake()


def stop() -> None:
    global _instance
    if _instance:
        _instance.stop()
        _instance = None
