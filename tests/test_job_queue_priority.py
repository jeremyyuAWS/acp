"""Discovery work overtakes content work in the shared job queue.

THE GAP THIS CLOSES. `claim_job` has always ordered by (priority, run_after), and idx_jobs_claim2
indexes exactly that — but every job was enqueued at the default 100, so the queue was pure FIFO.
A Discovery job arriving during an Assess fan-out waited behind every scan_file already queued,
which on a large estate is thousands of downloads. Nothing surfaced the wait: the scan showed as
"queued" with no indication of what it was queued behind.

RELATIONSHIP TO THE RESERVED LANE (#1121). These are complementary, not alternatives, and the
tests below assert both halves:

  * The reserved lane (ACP_DISCOVERY_RESERVED_WORKERS) gives Discovery a slot that content work
    can never occupy. It guarantees a floor, but it is opt-in, costs a general-purpose slot, and
    idles whenever no Discovery job exists.
  * Priority makes EVERY slot prefer Discovery when there is any, at no capacity cost, with the
    reservation off.

The load-bearing assertion is the ORDER a general worker claims in — not the stored integer. A
test that only checked the column would pass against a `job_priority` that returned the right
number while `claim_job` ignored it.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

import store as store_mod  # noqa: E402
from worker import JobWorker  # noqa: E402

CONTENT = ("scan_file", "scan_batch", "remediate_file", "scan_assess", "scan_finalize")
DISCOVERY = ("scan_discover", "scan_folder", "scan")


# ── the table ────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("job_type", DISCOVERY)
def test_discovery_types_outrank_the_default(job_type):
    assert store_mod.job_priority(job_type) == store_mod.DISCOVERY_JOB_PRIORITY
    assert store_mod.job_priority(job_type) < store_mod.DEFAULT_JOB_PRIORITY


@pytest.mark.parametrize("job_type", CONTENT)
def test_content_types_keep_the_default(job_type):
    assert store_mod.job_priority(job_type) == store_mod.DEFAULT_JOB_PRIORITY


def test_an_unknown_type_is_not_promoted():
    """Fail closed. A new job type added later must not silently inherit Discovery precedence
    just because nobody remembered this table exists."""
    assert store_mod.job_priority("some_future_job") == store_mod.DEFAULT_JOB_PRIORITY


# ── it reaches the row ───────────────────────────────────────────────────────────────────────
def test_enqueue_applies_the_type_default(isolated_store):
    disc = isolated_store.enqueue_job("scan_discover", {})
    content = isolated_store.enqueue_job("scan_file", {})
    assert isolated_store.get_job(disc)["priority"] == store_mod.DISCOVERY_JOB_PRIORITY
    assert isolated_store.get_job(content)["priority"] == store_mod.DEFAULT_JOB_PRIORITY


def test_an_explicit_priority_still_wins(isolated_store):
    """The type table decides only what happens when a caller says nothing. An explicit value —
    which is how tests/test_discovery_reserved_capacity.py constructs its fixtures — must be
    honoured exactly, including one that DEMOTES a discovery job."""
    jid = isolated_store.enqueue_job("scan_discover", {}, priority=100)
    assert isolated_store.get_job(jid)["priority"] == 100
    jid2 = isolated_store.enqueue_job("scan_file", {}, priority=0)
    assert isolated_store.get_job(jid2)["priority"] == 0


def test_enqueue_scan_applies_it_too(isolated_store):
    """The durable start path (routes/scans.start_scan) goes through enqueue_scan, not
    enqueue_job — so the two need the same defaulting or the production path is the one that
    misses out."""
    _sid, job_id = isolated_store.enqueue_scan(
        "s-prio", "drive", "owner@example.com", "scan_discover", {"scan_id": "s-prio"})
    assert isolated_store.get_job(job_id)["priority"] == store_mod.DISCOVERY_JOB_PRIORITY


# ── the behaviour that matters ───────────────────────────────────────────────────────────────
def test_discovery_overtakes_a_content_backlog(isolated_store):
    """THE test. A general worker — no reserved lane, no job_types filter — must claim the
    Discovery job first even though 50 content jobs were queued before it.

    Asserted on claim ORDER, not on the stored integer: a `job_priority` that returned the right
    number while `claim_job` ignored it would pass every test above and none of this one.
    """
    for i in range(50):
        isolated_store.enqueue_job("scan_file", {"n": i})
    disc = isolated_store.enqueue_job("scan_discover", {})

    claimed = isolated_store.claim_job("general-1")
    assert claimed["id"] == disc, "a Discovery job queued last was not claimed first"
    # And the backlog is untouched, not consumed, by that claim.
    assert isolated_store.job_stats(owner=None)["queued"] == 50


def test_folder_jobs_overtake_too(isolated_store):
    """scan_folder is the enumeration itself — scan_discover fans out one per top-level folder.

    This is the half a reserved lane keyed on `scan_discover` alone does not cover: the entry job
    starts immediately, then its follow-on work drops into the general queue behind the backlog.
    Without this the lane covers the starting gun and not the race.
    """
    for i in range(20):
        isolated_store.enqueue_job("scan_file", {"n": i})
    folder = isolated_store.enqueue_job("scan_folder", {"folder_id": "f1"})
    assert isolated_store.claim_job("general-1")["id"] == folder


def test_two_discovery_jobs_stay_fifo_between_themselves(isolated_store):
    """Precedence orders Discovery ahead of content; within Discovery, run_after still decides.
    Priority must not become a way for a later scan to jump an earlier one."""
    first = isolated_store.enqueue_job("scan_discover", {}, run_after="2020-01-01T00:00:00+00:00")
    isolated_store.enqueue_job("scan_discover", {}, run_after="2030-01-01T00:00:00+00:00")
    assert isolated_store.claim_job("general-1")["id"] == first


def test_content_still_drains_once_discovery_is_claimed(isolated_store):
    """Precedence, not starvation. Discovery jobs are few and short; once they are claimed the
    pool goes straight back to content work."""
    content = [isolated_store.enqueue_job("scan_file", {"n": i}) for i in range(3)]
    isolated_store.enqueue_job("scan_discover", {})

    assert isolated_store.claim_job("w")["type"] == "scan_discover"
    assert [isolated_store.claim_job("w")["id"] for _ in range(3)] == content


# ── the reserved lane still works, and now covers the fan-out ────────────────────────────────
def test_the_reserved_lane_covers_folder_jobs(isolated_store):
    """core.DISCOVERY_LANE_JOB_TYPES is what a reserved slot claims. It must include scan_folder,
    or the lane goes idle the moment the entry job fans out."""
    import core
    assert "scan_discover" in core.DISCOVERY_LANE_JOB_TYPES
    assert "scan_folder" in core.DISCOVERY_LANE_JOB_TYPES

    isolated_store.enqueue_job("scan_file", {})
    folder = isolated_store.enqueue_job("scan_folder", {})
    claimed = isolated_store.claim_job("lane", job_types=core.DISCOVERY_LANE_JOB_TYPES)
    assert claimed["id"] == folder


def test_the_reserved_lane_still_refuses_content(isolated_store):
    """The guarantee #1121 added, re-asserted here because this PR widened the lane's type list —
    widening it to something that could accept content work would silently undo it."""
    import core
    jid = isolated_store.enqueue_job("scan_file", {})
    w = JobWorker(isolated_store, job_types=core.DISCOVERY_LANE_JOB_TYPES)
    assert not w.run_once()
    assert isolated_store.get_job(jid)["status"] == "queued"
