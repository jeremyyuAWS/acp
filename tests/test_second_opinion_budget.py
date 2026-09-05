def _policy(**overrides):
    return {
        "max_requests_per_scan": 2, "max_requests_per_day": 3,
        "max_daily_cost_usd": 1.0, "estimated_cost_per_request_usd": 0.25,
        **overrides,
    }


def test_scan_request_ceiling_is_enforced(isolated_store):
    s = isolated_store
    assert s.reserve_second_opinion(scan_id="s1", file="a", policy=_policy())[0]
    assert s.reserve_second_opinion(scan_id="s1", file="b", policy=_policy())[0]
    assert not s.reserve_second_opinion(scan_id="s1", file="c", policy=_policy())[0]


def test_duplicate_document_never_spends_twice(isolated_store):
    s = isolated_store
    assert s.reserve_second_opinion(scan_id="s1", file="a", policy=_policy())[0]
    assert not s.reserve_second_opinion(scan_id="s1", file="a", policy=_policy())[0]


def test_daily_estimated_cost_ceiling_is_enforced(isolated_store):
    s = isolated_store
    policy = _policy(max_requests_per_scan=10, max_requests_per_day=10,
                     max_daily_cost_usd=.5)
    assert s.reserve_second_opinion(scan_id="s1", file="a", policy=policy)[0]
    assert s.reserve_second_opinion(scan_id="s2", file="b", policy=policy)[0]
    assert not s.reserve_second_opinion(scan_id="s3", file="c", policy=policy)[0]
