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
