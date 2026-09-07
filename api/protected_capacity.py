"""Pure capacity arithmetic for queue workers that must drain claimed work safely.

This module deliberately knows nothing about a database, KEDA, or Azure.  A future
controller can obtain active claim ownership from whichever control plane is
authoritative and use this model without making the arithmetic another deployment-
specific implementation detail.

The protected minimum is the number of distinct worker instances that own active
claims.  Several claims owned by one instance require one replica, not one replica per
claim.  A claim with no usable owner is counted separately and conservatively: merging
unknown owners could scale away a worker that is still processing it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class CapacityDecision:
    """The desired replica count and the facts needed to explain it."""

    desired_replicas: int
    soft_minimum: int
    protected_replicas: int
    queue_replicas: int
    maximum_replicas: int
    protection_shortfall: int

    @property
    def ceiling_limited(self) -> bool:
        """Whether the configured ceiling prevents full active-work protection."""
        return self.protection_shortfall > 0


def protected_replicas(active_claim_owners: Iterable[str | None]) -> int:
    """Return replicas that must remain while the supplied claims are active.

    Non-empty owner values are worker-instance identities. Repeated identities collapse
    to one replica. Each absent or blank identity consumes one conservative slot because
    there is no evidence that two such claims belong to the same worker.
    """
    known: set[str] = set()
    unknown = 0
    for owner in active_claim_owners:
        if owner is None or not str(owner).strip():
            unknown += 1
        else:
            known.add(str(owner).strip())
    return len(known) + unknown


def decide_capacity(
    *,
    scheduled_floor: int,
    queue_replicas: int,
    maximum_replicas: int,
    active_claim_owners: Iterable[str | None] = (),
) -> CapacityDecision:
    """Combine schedule, queue demand, and claimed-work protection.

    The schedule is a soft minimum: queue demand may raise capacity above it, while
    active claims prevent scale-down during drain. The maximum remains a hard platform
    safety limit. If it is lower than protected demand, ``protection_shortfall`` makes
    that unsafe configuration observable to the controller instead of silently implying
    that every active owner is protected.
    """
    values = {
        "scheduled_floor": scheduled_floor,
        "queue_replicas": queue_replicas,
        "maximum_replicas": maximum_replicas,
    }
    for name, value in values.items():
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{name} must be a non-negative integer")

    protected = protected_replicas(active_claim_owners)
    soft_minimum = max(scheduled_floor, protected)
    desired = min(maximum_replicas, max(soft_minimum, queue_replicas))
    return CapacityDecision(
        desired_replicas=desired,
        soft_minimum=soft_minimum,
        protected_replicas=protected,
        queue_replicas=queue_replicas,
        maximum_replicas=maximum_replicas,
        protection_shortfall=max(0, protected - maximum_replicas),
    )
