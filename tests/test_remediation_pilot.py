import json

import remediation_pilot as pilot


class Store:
    def __init__(self, policy=None, model=None):
        self.raw = json.dumps(policy or {})
        self.model = model or {}
    def get_setting(self, _key, _default=None): return self.raw
    def ai_cost_rollup(self, since_days=None, surface=None):
        assert since_days == 30
        assert surface == "remediation-pilot"
        return {"by_model": [self.model] if self.model else []}


def configured(**overrides): return {**pilot.DEFAULT_POLICY, "enabled": True, **overrides}


def model(**overrides):
    return {"provider": "anthropic", "model": "claude-sonnet-5", "zone": "cloud",
            "calls": 0, "failed": 0, "cost_usd": 0,
            "reviewed": {"decisions": 0, "approved": 0, "edited": 0, "rejected": 0},
            "validation": {"validated": 0, "cleared": 0, "regressed": 0,
                           "newly_failing": 0}, **overrides}


def test_pilot_defaults_off_and_only_approved_categories_exist():
    status = pilot.pilot_status(Store())
    assert status["running"] is False
    assert status["categories"] == ["docx:2.4.4", "html:2.4.4"]
    assert pilot.decision(Store(), "pptx", "2.4.4")["allowed"] is False


def test_armed_pilot_routes_only_the_two_approved_lanes_to_sonnet():
    store = Store(configured())
    assert pilot.decision(store, ".docx", "2.4.4")["model"] == "claude-sonnet-5"
    assert pilot.decision(store, "html", "2.4.4")["allowed"] is True
    assert pilot.decision(store, "docx", "2.4.9")["allowed"] is False


def test_any_post_write_regression_stops_immediately_before_minimum_sample():
    status = pilot.pilot_status(Store(configured(), model=model(
        calls=1, validation={"validated": 1, "cleared": 0, "regressed": 1,
                             "newly_failing": 1})))
    assert status["running"] is False
    assert "Post-write validation found a regression" in status["stop_reasons"]


def test_quality_thresholds_are_server_enforced():
    status = pilot.pilot_status(Store(configured(max_calls=50), model=model(
        calls=20, failed=3, cost_usd=1.25,
        reviewed={"decisions": 20, "approved": 12, "edited": 3, "rejected": 5},
        validation={"validated": 20, "cleared": 18, "regressed": 0,
                    "newly_failing": 0})))
    assert status["running"] is False
    assert "Model failure rate crossed the stop threshold" in status["stop_reasons"]
    assert "Reviewer acceptance fell below the stop threshold" in status["stop_reasons"]
    assert "Validation clear rate fell below the stop threshold" in status["stop_reasons"]


def test_policy_drops_unapproved_categories_in_storage_normalization():
    normalized = pilot.normalize_policy(configured(categories=["docx:2.4.4", "pdf:1.1.1"]))
    assert normalized["categories"] == ["docx:2.4.4"]
