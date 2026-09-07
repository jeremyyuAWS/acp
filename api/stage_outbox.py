"""Reliable delivery loop for canonical stage outbox messages.

The database owns retries and deduplication identity.  A publisher is deliberately a small
callable boundary so production transports and tests share identical claim/ack/failure logic.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import uuid


@dataclass(frozen=True)
class DispatchResult:
    claimed: int = 0
    delivered: int = 0
    retrying: int = 0
    dead_lettered: int = 0
    stale: int = 0


def dispatch_once(store, publish: Callable[[str, dict, str], str | None], *,
                  dispatcher_id: str | None = None, limit: int = 50,
                  lease_seconds: int = 60, max_attempts: int = 8,
                  backoff_seconds: int = 5) -> DispatchResult:
    """Deliver one bounded page.

    ``publish(topic, payload, message_id)`` must return an optional transport acknowledgement.
    It may be called again after an ambiguous process/network failure; the stable message id is
    the consumer's deduplication key.
    """
    dispatcher_id = dispatcher_id or f"outbox-{uuid.uuid4().hex[:12]}"
    messages = store.claim_stage_outbox(dispatcher_id, limit=limit,
                                        lease_seconds=lease_seconds)
    delivered = retrying = dead = stale = 0
    for message in messages:
        try:
            ack = publish(message["topic"], message["payload"], message["message_id"])
            if store.acknowledge_stage_outbox(message["message_id"], dispatcher_id,
                                              delivery_ack=ack):
                delivered += 1
            else:
                stale += 1
        except Exception as exc:  # noqa: BLE001 — delivery failures are durable data
            outcome = store.fail_stage_outbox(
                message["message_id"], dispatcher_id, str(exc), max_attempts=max_attempts,
                backoff_seconds=backoff_seconds)
            if outcome == "retry":
                retrying += 1
            elif outcome == "dead":
                dead += 1
            else:
                stale += 1
    return DispatchResult(len(messages), delivered, retrying, dead, stale)


def publish_database_job(store, topic: str, payload: dict, message_id: str) -> str:
    """Acknowledge that an outbox message's durable database job is claimable.

    ACP's production transport is the shared jobs table: workers claim it directly rather than
    consuming a separate broker topic.  The outbox still provides delivery acknowledgement and
    retry/dead-letter visibility, but it may only be acknowledged after the referenced job,
    execution, work item, and topic agree.  A corrupt or partially migrated row retries visibly.
    """
    job_id = str(payload.get("job_id") or "")
    execution_id = str(payload.get("execution_id") or "")
    work_item_id = str(payload.get("work_item_id") or "")
    if not job_id or not execution_id or not work_item_id:
        raise ValueError(f"outbox message {message_id} is missing durable job identity")
    job = store.get_job(job_id)
    if not job:
        raise LookupError(f"outbox job does not exist: {job_id}")
    if job.get("type") != topic or job.get("batch_id") != execution_id:
        raise ValueError(f"outbox job identity does not match message: {message_id}")
    with store._db.cursor() as cur:
        store._db.execute(cur,
            "SELECT work_item_id FROM stage_work_items WHERE work_item_id=%s "
            "AND execution_id=%s AND job_id=%s", (work_item_id, execution_id, job_id))
        if not store._db.fetchone(cur):
            raise LookupError(f"outbox work item does not exist: {work_item_id}")
    return f"database-job:{job_id}"


def dispatch_database_jobs_once(store, **kwargs) -> DispatchResult:
    """Dispatch one production page using ACP's durable database queue transport."""
    return dispatch_once(store, lambda topic, payload, message_id:
                         publish_database_job(store, topic, payload, message_id), **kwargs)
