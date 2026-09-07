"""Executable contract for schedule + queue + active-claim capacity arithmetic."""
from __future__ import annotations

import pytest

from api.protected_capacity import decide_capacity, protected_replicas


def test_zero_queued_work_retains_every_replica_that_owns_active_work():
    decision = decide_capacity(
        scheduled_floor=0,
        queue_replicas=0,
        maximum_replicas=10,
        active_claim_owners=("worker-a", "worker-b", "worker-b"),
    )

    assert decision.protected_replicas == 2
    assert decision.soft_minimum == 2
    assert decision.desired_replicas == 2
    assert not decision.ceiling_limited


def test_capacity_drains_one_replica_as_each_active_owner_finishes():
    def desired(owners):
        return decide_capacity(
            scheduled_floor=0,
            queue_replicas=0,
            maximum_replicas=10,
            active_claim_owners=owners,
        ).desired_replicas

    assert desired(("worker-a", "worker-b", "worker-c")) == 3
    assert desired(("worker-a", "worker-c")) == 2
    assert desired(("worker-c",)) == 1
    assert desired(()) == 0


def test_work_hour_floor_is_soft_and_queue_demand_can_exceed_it():
    decision = decide_capacity(
        scheduled_floor=4,
        queue_replicas=7,
        maximum_replicas=12,
        active_claim_owners=("worker-a",),
    )

    assert decision.soft_minimum == 4
    assert decision.desired_replicas == 7


def test_hard_ceiling_is_respected_and_active_work_shortfall_is_explicit():
    decision = decide_capacity(
        scheduled_floor=8,
        queue_replicas=20,
        maximum_replicas=3,
        active_claim_owners=("worker-a", "worker-b", "worker-c", "worker-d"),
    )

    assert decision.desired_replicas == 3
    assert decision.protected_replicas == 4
    assert decision.protection_shortfall == 1
    assert decision.ceiling_limited


def test_duplicate_claims_on_one_worker_only_protect_one_replica():
    assert protected_replicas(("worker-a", "worker-a", "worker-a")) == 1


def test_claims_without_ownership_are_protected_conservatively():
    assert protected_replicas((None, "", "worker-a", None)) == 4


@pytest.mark.parametrize(
    "field,value",
    (("scheduled_floor", -1), ("queue_replicas", 1.5),
     ("maximum_replicas", True)),
)
def test_invalid_capacity_inputs_are_rejected(field, value):
    kwargs = dict(scheduled_floor=0, queue_replicas=0, maximum_replicas=10)
    kwargs[field] = value
    with pytest.raises(ValueError, match=field):
        decide_capacity(**kwargs)
