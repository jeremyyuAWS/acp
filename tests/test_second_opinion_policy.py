from second_opinion_policy import DEFAULT_POLICY, eligible, normalize_policy


def test_default_is_fail_closed():
    assert DEFAULT_POLICY["enabled"] is False
    assert normalize_policy(None)["enabled"] is False
    assert normalize_policy("not-json")["enabled"] is False


def test_criteria_and_threshold_are_both_required():
    policy = {"enabled": True, "criteria": ["1.3.5"], "confidence_threshold": "medium"}
    assert eligible(policy, "1.3.5", "low")
    assert eligible(policy, "1.3.5", "medium")
    assert not eligible(policy, "1.3.5", "high")
    assert not eligible(policy, "1.1.1", "low")


def test_policy_normalization_is_bounded_and_deduplicated():
    assert normalize_policy({
        "enabled": True,
        "criteria": [" 1.3.5 ", "1.3.5", "3.1.2"],
        "confidence_threshold": "unexpected",
        "secret": "must disappear",
    }) == {
        "enabled": True,
        "criteria": ["1.3.5", "3.1.2"],
        "confidence_threshold": "low",
    }
