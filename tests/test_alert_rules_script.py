"""The alert rules deploy/public/alert-rules.sh creates, checked against what Azure can measure.

WHY THIS FILE. A metric alert rule naming a metric Azure does not collect is not an error. Azure
accepts the rule, the rule never fires, and Live Operations reports the service as monitored —
which is precisely the false green the alerts panel exists to prevent, arriving through the one
door that panel cannot see. The panel can only tell you a rule exists; it cannot tell you the rule
is watching something real. This test is the only place that is checked.

The second half is about honesty of naming. "Queue stalled" and "no worker heartbeat" are on the
Tier 5 wish list and are ACP-internal — they live in ACP's database, not in any Container Apps
metric — so a rule bearing one of those names, thresholded on some Azure metric that merely
correlates, would report the queue as monitored when nothing watches it.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ACP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ACP / "api"))

import routes.control as control

SCRIPT = ACP / "deploy" / "public" / "alert-rules.sh"


def _conditions() -> list[tuple[str, str, str, str]]:
    """(aggregation, metric, operator, threshold) for every --condition in the script."""
    text = SCRIPT.read_text()
    found = re.findall(r'"(\w+) (\w+) ([<>]=?) ([\d.]+)"', text)
    return [(agg, metric, op, thr) for agg, metric, op, thr in found]


def test_the_script_exists_and_is_executable():
    assert SCRIPT.exists(), "the alert rules have no provisioning script"
    assert SCRIPT.stat().st_mode & 0o111, "not executable — an operator has to guess how to run it"


def test_the_walk_found_the_conditions():
    """Anti-vacuity: every assertion below passes on an empty list, so prove the parse worked."""
    conditions = _conditions()
    assert len(conditions) >= 5, f"only parsed {len(conditions)} conditions — the regex is stale"


def test_every_rule_thresholds_on_a_metric_azure_actually_collects():
    """The failure this file exists for. A typo'd metric name yields a rule that is accepted,
    never fires, and makes an unwatched service read as watched.

    Checked against `_AZ_METRICS` in api/routes/control.py rather than a second hand-written list,
    because that tuple is the set this repo has already verified against Microsoft's supported-
    metrics reference — and a rule watching a metric the API does not read would be invisible in
    the drawer for the opposite reason.
    """
    known = {row[0] for row in control._AZ_METRICS}
    unknown = sorted({m for _agg, m, _op, _thr in _conditions() if m not in known})
    assert not unknown, (
        f"alert rules threshold on metric(s) Azure Monitor is not known to collect: {unknown}.\n"
        f"Known (api/routes/control.py _AZ_METRICS): {sorted(known)}")


def test_each_condition_uses_the_aggregation_that_metric_carries():
    """`total RestartCount` and `average RestartCount` are different questions, and only one of
    them is answerable — a counter read as an average reports a restarting app as a calm one. The
    API already had to pick the right aggregation per metric to read the values back; a rule that
    picks a different one is thresholding on a number nobody else computes."""
    expected = {row[0]: row[2] for row in control._AZ_METRICS}   # rest name -> aggregation
    wrong = [(m, agg, expected[m]) for agg, m, _op, _thr in _conditions()
             if m in expected and agg.lower() != expected[m].lower()]
    assert not wrong, ("alert conditions disagree with the aggregation the API reads for the same "
                       f"metric (metric, rule uses, API reads): {wrong}")


def test_no_rule_claims_to_watch_a_condition_azure_cannot_see():
    """Naming honesty. A rule called "queue-stalled" makes the drawer report the queue as
    monitored; no Container Apps metric can see ACP's job queue, so the rule would be watching
    something else entirely under that name."""
    text = SCRIPT.read_text()
    names = set(re.findall(r'create_rule "\$app" ([\w-]+)', text))
    forbidden = {"queue-stalled", "queue-stall", "no-heartbeat", "heartbeat",
                 "job-retries", "job-failures", "stalled"}
    assert not (names & forbidden), (
        f"rule name(s) {sorted(names & forbidden)} promise a condition no Container Apps metric "
        "reports. Those need a custom metric or an Application Insights log alert.")
    assert names, "no rules parsed — the regex is stale"


def test_the_script_says_out_loud_what_it_does_not_create():
    """The omission is only honest if it is written down. Otherwise the next person adds a
    'queue-stalled' rule on whatever metric is nearest, and the drawer starts lying."""
    text = SCRIPT.read_text()
    assert "queue stalled" in text.lower()
    assert "worker heartbeat" in text.lower()


def test_a_missing_replica_is_the_only_critical():
    """Severity 0 is Azure's most severe and reads as "the product is down". Spending it on CPU
    saturation is how a severity scale stops meaning anything. Zero replicas — no work happening
    at all, silently — is the one that earns it."""
    text = SCRIPT.read_text()
    criticals = re.findall(r'create_rule "\$app" ([\w-]+) 0 ', text)
    assert criticals == ["no-replicas"], f"severity 0 spent on: {criticals}"


def test_the_apps_match_the_worker_services_the_api_reads():
    """A rule is matched to a service in the drawer by resource id. An app the script skips shows
    as unmonitored — correctly, but silently — so the two lists have to be kept in step."""
    text = SCRIPT.read_text()
    default = re.search(r'WORKER_APP_NAMES_SPACED:-([^}]+)\}', text)
    assert default, "the default app list is not where this test expects it"
    apps = default.group(1).split()
    assert len(apps) >= 3, apps
    assert all(a.startswith("acp-") for a in apps), apps
