"""Best-effort per-process worker telemetry shared by both supported entry points."""
from __future__ import annotations

import os
import threading
from datetime import datetime, timezone

from swallowed import swallowed


class WorkerInstanceReporter:
    """Publish one process row without allowing telemetry to affect customer work."""

    def __init__(self, core_module, *, interval_seconds: float | None = None):
        self.core = core_module
        self.interval_seconds = (interval_seconds if interval_seconds is not None else
            min(15.0, max(1.0, core_module.WORKER_INSTANCE_FRESHNESS_SECONDS / 2)))
        self.store = core_module.get_store()
        self.role = (os.environ.get("ACP_WORKER_ROLE") or "mixed").strip().lower()
        self.process_id = core_module.worker_process_instance_id(self.role)
        self.replica_id = core_module._replica_id()
        self.revision = (os.environ.get("CONTAINER_APP_REVISION") or "unknown").strip()
        self.version = (os.environ.get("ACP_BUILD_VERSION") or "").strip() or "dev"
        self.started_at = datetime.now(timezone.utc).isoformat()
        self._last_state = None
        self._stop = threading.Event()
        self._thread = None

    def _pool(self):
        handles = list(self.core._worker_handles)
        active_workers = [worker for worker, _thread in handles
                          if worker.active_job_id is not None]
        # job_types=None means the slot accepts every registered handler. Reporting [] used to
        # say the exact opposite: that an unrestricted mixed pool supported no work.
        if any(worker.job_types is None for worker, _thread in handles):
            from worker import HANDLERS
            supported = sorted(HANDLERS)
        else:
            supported = sorted({kind for worker, _thread in handles
                                for kind in (worker.job_types or ())})
        unhealthy = any(getattr(worker, "unhealthy", False) for worker, _thread in handles)
        return handles, active_workers, supported, unhealthy

    def record(self, state: str | None = None) -> None:
        handles, active_workers, supported, unhealthy = self._pool()
        concurrency = len(handles)
        active = len(active_workers)
        effective_state = state or ("unhealthy" if unhealthy else "busy" if active else "ready")
        now = datetime.now(timezone.utc).isoformat()
        self.store.upsert_worker_instance(
            self.process_id, replica_id=self.replica_id, revision_name=self.revision,
            started_at=self.started_at, last_heartbeat_at=now,
            supported_job_types=supported, concurrency_limit=concurrency,
            active_job_count=active, available_slots=max(0, concurrency - active),
            state=effective_state,
            last_claimed_job_id=next((worker.active_job_id for worker in active_workers), None),
            software_version=self.version)
        if effective_state != self._last_state:
            try:
                self.store.append_orchestration_event(
                    owner_email="system", kind=f"worker.{effective_state}",
                    worker_id=self.process_id, replica_id=self.replica_id,
                    revision_name=self.revision,
                    detail={"role": self.role, "busy_slots": active,
                            "worker_slots": concurrency})
            except Exception:
                swallowed("worker lifecycle event failed")
            self._last_state = effective_state

    def _run(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            try:
                self.record()
            except Exception:
                swallowed("worker telemetry heartbeat failed")

    def start(self) -> None:
        try:
            self.record("starting")
            self.record()
        except Exception:
            swallowed("worker telemetry registration failed")
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="worker-instance-heartbeat")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        try:
            self.record("draining")
        except Exception:
            swallowed("worker telemetry drain state failed")

    def offline(self) -> None:
        try:
            self.record("offline")
        except Exception:
            swallowed("worker telemetry offline state failed")
