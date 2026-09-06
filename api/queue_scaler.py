"""The SQL a KEDA postgresql scaler runs, defined once.

WHY THIS MODULE EXISTS. Three places in this repository hand a KEDA `postgresql` scaler a
literal SQL query against the `jobs` table — `deploy/public/deploy.sh`,
`deploy/public/rightsize-production.sh` and `packaging/chart/acp/templates/autoscaling.yaml` —
and every one of them counted a DIFFERENT population from the one a worker can actually claim.

`store.claim_job` claims a row only when ALL THREE of these hold:

    status='queued'  AND  run_after <= now  AND  attempts < max_attempts

The three scalers tested only the first. That is not a cosmetic difference; it is the
difference between a queue depth and a number that cannot go down:

  * `run_after` is how retry backoff is expressed (`store.fail_job` writes
    `now + backoff_seconds`, and the backoff runs up to 600s). A job waiting out its backoff is
    counted as depth by a scaler that ignores `run_after`, so the tier scales up for work no
    replica is allowed to take, and the new replicas idle until the cooldown removes them.
  * `attempts >= max_attempts` rows sit at `status='queued'` until the reaper marks them dead
    (`store.reap_exhausted_jobs`). They are permanently unclaimable. Counted as depth, they are
    a floor the number can never fall below.
  * The oldest-job-age trigger in the Helm chart is the worse of the two, because age has no
    ceiling. One unclaimable row pins that trigger — and therefore the tier — at maximum
    replicas indefinitely, while the backlog it is supposedly reacting to is empty.

The PRD this serves ("Settings -> Scheduling", §6.2) already names retry eligibility as an
input scaling must consider. The implementation did not consider it. So the predicate lives
here, once, and `scripts/gen_queue_scalers.py --check` holds the three copies to it.

WHY THE CAST. `jobs.run_after` is a TEXT column holding a UTC ISO-8601 string with an offset
(`store.enqueue_job` writes `datetime.now(timezone.utc).isoformat()`, `store.fail_job` writes
the same shape plus a timedelta). The application compares it lexicographically against another
string of that shape, which is correct for that encoding and unavailable to SQL that wants to
compare against `now()`. Casting the column — `run_after::timestamptz <= now()` — is the exact
mirror: a NULL casts to NULL and is excluded, which is what `run_after <= %s` does too.

Two things this deliberately does NOT do. It does not use `to_char(now(), ...)` to build the
application's string encoding in SQL: that reproduces a serialisation format in a second place
and breaks silently when either side's microsecond or offset rendering differs. And it does not
add `IS NOT NULL`, because `claim_job` has no such clause and a scaler that counts rows the
worker will not claim is the whole defect above.
"""
from __future__ import annotations

# The claim predicate, as SQL, mirroring store.claim_job's WHERE clause term for term.
#
# Kept as one string rather than assembled from parts so that a reader comparing it against
# claim_job is comparing two things of the same shape. If claim_job's eligibility changes, this
# changes with it — tests/test_queue_scaler.py reads claim_job's source and fails otherwise.
ELIGIBLE_SQL = "status='queued' AND run_after::timestamptz <= now() AND attempts < max_attempts"

# The part of ELIGIBLE_SQL the three deployed copies already had. Split out because the existing
# guards in tests/test_db_connection_budget.py and tests/test_packaging_chart.py match on this
# prefix, and because it names precisely what was missing.
STATUS_SQL = "status='queued'"
CLAIMABILITY_SQL = "run_after::timestamptz <= now() AND attempts < max_attempts"


def _types_sql(job_types) -> str:
    """`'a', 'b'` — the inside of a `type IN (...)` list, in the order given.

    ORDER IS PRESERVED, not sorted. The lane tuples in api/core.py are ordered deliberately
    (REMEDIATE_LANE_JOB_TYPES leads with remediate_file, the job the lane is named for) and a
    generated query that reorders them would produce a spurious diff against a hand-written one
    every time somebody compared the two.
    """
    types = tuple(job_types)
    if not types:
        raise ValueError("a queue scaler with no job types would count every lane's backlog")
    return ", ".join("'" + str(t).replace("'", "''") + "'" for t in types)


def depth_query(job_types) -> str:
    """How many jobs of this lane a worker could claim right now.

    KEDA divides this by `targetQueryValue` and asks for that many replicas, so it must count
    CLAIMABLE work: a depth that includes jobs in retry backoff asks for replicas that will find
    nothing to do.
    """
    return (f"SELECT count(*) FROM jobs WHERE {STATUS_SQL} AND type IN ({_types_sql(job_types)}) "
            f"AND {CLAIMABILITY_SQL}")


def oldest_age_query(job_types) -> str:
    """Seconds the oldest CLAIMABLE job of this lane has been waiting, or 0 when there is none.

    Depth alone under-reacts to a stalled queue (three jobs held forty minutes is worse than
    thirty held ten seconds), which is why the chart pairs the two triggers. Age is also where
    an ineligible row does the most damage: it has no upper bound, so one unclaimable job pins
    the tier at max replicas for as long as the row exists.

    `created_at` rather than `run_after`: the question is how long the work has been waiting,
    not how long since its last retry was scheduled.
    """
    return ("SELECT COALESCE(EXTRACT(EPOCH FROM (now() - MIN(created_at::timestamptz))), 0)::int "
            f"FROM jobs WHERE {STATUS_SQL} AND type IN ({_types_sql(job_types)}) "
            f"AND {CLAIMABILITY_SQL}")


def lane_job_types() -> dict:
    """The three worker lanes, from api/core.py's own tuples.

    Imported lazily and inside the function: `core` pulls in the store, the worker pool and the
    connectors, and this module is imported by a generator script that must run without a
    database. Callers that already have the tuples should pass them to the query builders
    directly instead.
    """
    import core  # noqa: PLC0415 — see docstring
    return {
        "discovery": core.DISCOVERY_LANE_JOB_TYPES,
        "assess": core.ASSESS_LANE_JOB_TYPES,
        "remediate": core.REMEDIATE_LANE_JOB_TYPES,
    }
