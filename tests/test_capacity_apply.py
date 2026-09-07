from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))

import capacity_apply as apply  # noqa: E402
from capacity_policy import AppPolicy, ScaleRule  # noqa: E402


def policy(app="acp-assess", maximum=10):
    return AppPolicy(app=app, service="assess", min_replicas=1, max_replicas=maximum,
                     rules=(ScaleRule("business-hours", "cron",
                                      {"timezone": "America/Los_Angeles",
                                       "start": "0 6 * * 1,2,3,4,5",
                                       "end": "0 20 * * 1,2,3,4,5",
                                       "desiredReplicas": "4"}),
                            ScaleRule("assess-queue", "postgresql",
                                      {"query": "SELECT 1", "targetQueryValue": "8"},
                                      {"connection": "database-url"})))


def scale_for(p):
    desired = apply.desired_policy(p)
    return {"min_replicas": desired["min_replicas"],
            "max_replicas": desired["max_replicas"], "rules": desired["rules"]}


def test_hash_is_canonical_and_excludes_auth_and_secrets():
    first = policy()
    normal = apply.desired_policy(first)
    assert "auth" not in str(normal)
    assert "database-url" not in str(normal)
    reordered = {**normal, "rules": list(reversed(normal["rules"]))}
    # Dict ordering is canonical. Rule ordering is canonicalised at the typed boundary.
    assert apply.policy_hash(normal) == apply.policy_hash({k: normal[k] for k in reversed(normal)})
    assert apply.policy_hash(first) == apply.policy_hash(normal)
    assert apply.policy_hash(normal) != apply.policy_hash(reordered)
    tainted = {**normal, "password": "do-not-retain"}
    assert "do-not-retain" not in apply._canonical_json(apply._safe_value("policy", tainted))


def test_comparison_is_order_independent_and_checks_complete_rules():
    wanted = policy()
    observed = scale_for(wanted)
    observed["rules"].reverse()
    assert apply.compare(wanted, observed)["state"] == "matched"
    observed["rules"].append({"name": "unexpected", "type": "cpu", "metadata": {"value": "50"}})
    result = apply.compare(wanted, observed)
    assert result["state"] == "drifted"
    assert result["differences"][0]["field"] == "rules"


def test_unreadable_is_not_reported_as_drift():
    result = apply.compare(policy(), None)
    assert result["state"] == "unreadable"
    assert result["observed_hash"] is None


class FakeGateway:
    def __init__(self, scales, fail_app=None, mismatch_app=None):
        self.scales = dict(scales)
        self.fail_app = fail_app
        self.mismatch_app = mismatch_app
        self.applied = []

    def read_scale(self, app):
        return self.scales.get(app)

    def apply_scale(self, policy):
        if policy.app == self.fail_app:
            raise RuntimeError("password=must-not-escape")
        self.applied.append(policy.app)
        self.scales[policy.app] = scale_for(policy)
        if policy.app == self.mismatch_app:
            self.scales[policy.app]["max_replicas"] += 1


def test_apply_preflights_every_app_before_any_write():
    policies = [policy("one"), policy("two")]
    gateway = FakeGateway({"one": scale_for(policies[0])})
    result = apply.apply_policies(policies, gateway)
    assert result["state"] == "preflight_failed"
    assert gateway.applied == []


def test_apply_records_verified_per_app_success():
    policies = [policy("one"), policy("two")]
    gateway = FakeGateway({p.app: scale_for(p) for p in policies})
    result = apply.apply_policies(policies, gateway)
    assert result["state"] == "applied"
    assert [row["status"] for row in result["apps"]] == ["applied", "applied"]
    assert all(row["desired_hash"] == row["observed_hash"] for row in result["apps"])


def test_apply_failure_is_sanitized_and_stops_later_apps():
    policies = [policy("one"), policy("two"), policy("three")]
    gateway = FakeGateway({p.app: scale_for(p) for p in policies}, fail_app="two")
    result = apply.apply_policies(policies, gateway)
    assert result["state"] == "partial"
    assert gateway.applied == ["one"]
    assert [row["status"] for row in result["apps"]] == ["applied", "apply_failed", "not_applied"]
    assert result["apps"][1]["error_code"] == "RuntimeError"
    assert "password" not in str(result)


def test_readback_mismatch_stops_later_apps_and_reports_drift():
    policies = [policy("one"), policy("two")]
    gateway = FakeGateway({p.app: scale_for(p) for p in policies}, mismatch_app="one")
    result = apply.apply_policies(policies, gateway)
    assert result["state"] == "partial"
    assert [row["status"] for row in result["apps"]] == ["drifted", "not_applied"]
    assert gateway.applied == ["one"]
