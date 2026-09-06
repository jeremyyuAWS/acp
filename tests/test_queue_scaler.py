"""The queue-scaler SQL must count the jobs a worker can actually claim.

WHAT WENT WRONG, AND WHY NOTHING CAUGHT IT. Four KEDA `postgresql` scaler queries live in this
tree — two in deploy/public/rightsize-production.sh, one in deploy/public/deploy.sh, two triggers
in packaging/chart/acp/templates/autoscaling.yaml. The job-type lists in them were already
guarded (tests/test_packaging_chart.py reads api/core.py's own lane tuples). The ELIGIBILITY
predicate was not, and every copy had the same hole: they counted `status='queued'` while
`store.claim_job` claims on

    status='queued' AND run_after <= now AND attempts < max_attempts

so both a job sitting out its retry backoff (up to 600s) and an attempts-exhausted row waiting
for the reaper were counted as queue depth. The tier scales up for work no replica is allowed to
take; on the oldest-job-age trigger, where the number has no ceiling, one such row pins the tier
at maxReplicas indefinitely against an empty queue.

The tests here hold the predicate to claim_job's, and hold the deployed copies to the predicate.
"""
from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))
sys.path.insert(0, str(ROOT / "scripts"))

import queue_scaler as qs  # noqa: E402


def _claim_job_source() -> str:
    """The body of store.claim_job, as text.

    Read from source rather than executed: claim_job needs a database, and the thing under test
    is the SQL it *contains*. Sliced at the next `def` at the same indentation so a later method's
    SQL cannot satisfy an assertion about this one.
    """
    source = (ROOT / "api" / "store.py").read_text()
    start = source.index("    def claim_job(self, worker_id: str")
    end = source.index("\n    def ", start + 1)
    return source[start:end]


def test_the_predicate_mirrors_the_claim_query_term_for_term():
    """Every term claim_job requires must appear in the scaler's predicate.

    Matched loosely on whitespace and quoting because the two are written for different
    consumers — a parameterised psycopg2 statement and a literal KEDA metadata string — and an
    assertion that demanded identical text would fail on a space.
    """
    body = _claim_job_source()
    assert "qj.status='queued'" in body
    assert "qj.run_after<=%s" in body
    assert "qj.attempts < qj.max_attempts" in body

    predicate = qs.ELIGIBLE_SQL
    assert "status='queued'" in predicate
    assert "run_after" in predicate and "now()" in predicate
    assert "attempts < max_attempts" in predicate


def test_the_predicate_casts_the_column_rather_than_formatting_the_clock():
    """`jobs.run_after` is TEXT holding an ISO-8601 string, so the comparison needs a cast.

    The tempting alternative — building the application's string encoding in SQL with to_char —
    reproduces a serialisation format in a second place and breaks silently whenever either
    side's microsecond or offset rendering differs. `(now() AT TIME ZONE 'utc')::text` is worse
    still: it renders a SPACE separator where the application writes 'T', and 'T' sorts above
    ' ', so every job would compare as not-yet-eligible and the scaler would read zero forever.
    """
    assert "run_after::timestamptz <= now()" in qs.ELIGIBLE_SQL
    assert "to_char" not in qs.ELIGIBLE_SQL
    assert "AT TIME ZONE" not in qs.ELIGIBLE_SQL


def test_run_after_is_written_as_an_iso_string_which_is_what_makes_the_cast_correct():
    """The bite check for the cast: if run_after stopped being an ISO-8601 string, the cast in
    ELIGIBLE_SQL would be wrong and this test is what says so."""
    store = (ROOT / "api" / "store.py").read_text()
    assert "run_after TEXT" in store, "jobs.run_after is no longer a TEXT column"
    assert "run_after = (now + timedelta(seconds=backoff_seconds)).isoformat()" in store, (
        "store.fail_job no longer writes run_after as an ISO-8601 string")


def test_the_queries_name_every_job_type_they_are_given_in_order():
    types = ("remediate_file", "publish_file")
    depth = qs.depth_query(types)
    assert "type IN ('remediate_file', 'publish_file')" in depth
    assert depth.startswith("SELECT count(*) FROM jobs WHERE")
    age = qs.oldest_age_query(types)
    assert "MIN(created_at::timestamptz)" in age
    assert qs.CLAIMABILITY_SQL in age


def test_a_scaler_with_no_job_types_is_refused_rather_than_counting_every_lane():
    """An empty `type IN ()` is a Postgres syntax error, and dropping the clause entirely would
    scale one tier on another's backlog. Neither is a thing to emit quietly."""
    with pytest.raises(ValueError):
        qs.depth_query(())


def test_the_lane_tuples_come_from_the_application():
    import core
    lanes = qs.lane_job_types()
    assert lanes["discovery"] == core.DISCOVERY_LANE_JOB_TYPES
    assert lanes["assess"] == core.ASSESS_LANE_JOB_TYPES
    assert lanes["remediate"] == core.REMEDIATE_LANE_JOB_TYPES


def test_every_deployed_copy_matches_the_generator():
    import gen_queue_scalers as gen
    problems = gen.check()
    assert problems == [], "\n".join(problems)


def test_the_check_notices_a_copy_that_has_drifted(tmp_path, monkeypatch):
    """The bite check, without which the test above is satisfiable by a check that looks at
    nothing. Strips the claimability half out of copies of all three files and requires each one
    to be reported."""
    import gen_queue_scalers as gen

    for attr in ("RIGHTSIZE", "DEPLOY", "CHART"):
        original = getattr(gen, attr)
        target = tmp_path / original.name
        shutil.copy(original, target)
        target.write_text(target.read_text().replace(" AND " + qs.CLAIMABILITY_SQL, ""))
        monkeypatch.setattr(gen, attr, target)
    # ROOT is only used to shorten paths in the messages; relative_to would raise on tmp_path.
    monkeypatch.setattr(gen, "ROOT", tmp_path)

    problems = gen.check()
    # Four, not three: rightsize-production.sh carries TWO rules and each is reported by name.
    assert len(problems) == 4, problems
    joined = "\n".join(problems)
    assert "remediation-queue" in joined
    assert "assess-queue" in joined
    assert "jobs-queued" in joined
    assert "0 of 2 triggers" in joined


def test_the_rightsize_script_only_attaches_the_assess_rule_to_an_unpinned_tier():
    """A scale rule on a tier whose floor equals its ceiling cannot add a replica, and applying
    one costs a revision — a worker restart — for no behaviour. The script's guard and the
    script's own replica range are read from the same file so they cannot disagree."""
    script = (ROOT / "deploy/public/rightsize-production.sh").read_text()
    ranges = {
        m.group(1): (int(m.group(2)), int(m.group(3)))
        for m in re.finditer(r"^update_app\s+(\S+)\s+\S+\s+\S+\s+(\d+)\s+(\d+)", script, re.M)
    }
    call = re.search(r"^apply_assess_autoscale\s+(\d+)\s+(\d+)\s*$", script, re.M)
    assert call, "rightsize-production.sh no longer calls apply_assess_autoscale with a range"
    assert (int(call.group(1)), int(call.group(2))) == ranges["acp-assess"], (
        "apply_assess_autoscale is passed a different range from the one update_app applies to "
        "acp-assess — the guard would then answer for the wrong tier")
    assert 'if [[ "$floor" == "$ceiling" ]]; then' in script, (
        "the pinned-tier guard is gone: an inert scale rule would now be applied, paying a "
        "worker restart for a rule that cannot fire")
