"""Azure Cost Management actuals on the Live Operations cost panel.

`billing.configured` was hardcoded False and no Cost Management call existed anywhere, so the
panel could only ever show an estimate from a rate card. These pin the three things that make an
actual safe to display: it is parsed by COLUMN NAME, it is cached hard enough not to abuse a
rate-limited API from a panel that polls every 60 seconds, and it is never labelled live.
"""
from __future__ import annotations

import urllib.error

import pytest

from api.routes import costs as costs_module


@pytest.fixture(autouse=True)
def _clean_cache():
    costs_module._billing_cache.update({"at": 0.0, "value": None, "blocked_until": 0.0})
    yield
    costs_module._billing_cache.update({"at": 0.0, "value": None, "blocked_until": 0.0})


def _answer(columns, rows):
    return {"properties": {"columns": [{"name": n} for n in columns], "rows": rows}}


def _http_error(code, retry_after=None):
    headers = {"Retry-After": retry_after} if retry_after is not None else {}
    return urllib.error.HTTPError("https://x", code, "no", headers, None)


# -- parsing -----------------------------------------------------------------------------------

def test_reads_the_total_by_column_name_not_by_position():
    """The column order is not contractual.

    Reading row[0] as the cost is the mistake this guards: with the columns the other way round
    the first value is a CURRENCY STRING, and a currency coerced through float() does not fail
    loudly -- the total quietly disappears. Both orders must give the same answer.
    """
    cost_first = costs_module._total_from(_answer(["Cost", "Currency"], [[41.5, "USD"]]))
    currency_first = costs_module._total_from(_answer(["Currency", "Cost"], [["USD", 41.5]]))
    assert cost_first == (41.5, "USD")
    assert currency_first == (41.5, "USD")


def test_sums_multiple_rows_and_tolerates_alternate_column_spellings():
    total, currency = costs_module._total_from(
        _answer(["PreTaxCost", "BillingCurrency"], [[10.0, "EUR"], [5.25, "EUR"]]))
    assert total == 15.25
    assert currency == "EUR"


@pytest.mark.parametrize("payload", [
    None, {}, {"properties": {}},
    _answer([], []),
    _answer(["Cost", "Currency"], []),
    _answer(["Currency"], [["USD"]]),
    _answer(["Cost", "Currency"], [["not-a-number", "USD"]]),
])
def test_an_unanswerable_result_is_none_never_zero(payload):
    # A subscription whose cost could not be read has not spent nothing, and $0.00 rendered with
    # the same confidence as a real total is the one output worse than "unavailable".
    assert costs_module._total_from(payload) == (None, None)


# -- failure categories an operator can act on -------------------------------------------------

@pytest.mark.parametrize("code,reason", [(401, "permission"), (403, "permission"),
                                         (429, "throttled"), (500, "error"), (400, "error")])
def test_names_the_failure_category(monkeypatch, code, reason):
    def _raise(*a, **kw):
        raise _http_error(code, retry_after="120" if code == 429 else None)

    monkeypatch.setattr(costs_module.urllib.request, "urlopen", _raise)
    _payload, got, retry = costs_module._cost_post("/x", {}, "token")
    assert got == reason
    assert retry == (120.0 if code == 429 else None)


def test_a_permission_failure_says_which_role(monkeypatch):
    # 401/403 on Cost Management is a DIFFERENT grant from the Monitoring Reader role the metrics
    # path needs, and an operator told only "unavailable" will grant the wrong one.
    monkeypatch.setattr(costs_module, "_bearer_token", lambda: "token")
    monkeypatch.setattr(costs_module, "_cost_post", lambda *a, **kw: (None, "permission", None))
    block = costs_module._query_billing()
    assert block["configured"] is False
    assert block["actual_month_to_date_usd"] is None
    assert "Cost Management Reader" in block["freshness_label"]


def test_a_missing_token_does_not_raise_through_the_endpoint(monkeypatch):
    def _boom():
        raise RuntimeError("no managed identity")

    monkeypatch.setattr(costs_module, "_bearer_token", _boom)
    block = costs_module._query_billing()
    assert block["unavailable_reason"] == "credential"
    assert block["actual_month_to_date_usd"] is None


# -- the two calls are independent -------------------------------------------------------------

def test_a_failing_forecast_does_not_lose_the_actual(monkeypatch):
    """The forecast endpoint is the more fragile of the two.

    Trading a real month-to-date measurement for a projection that 400'd is exactly the wrong way
    round, so the calls are separate and only the forecast goes missing.
    """
    calls = []

    def _post(path, body, token):
        calls.append(path)
        if path.endswith("/query"):
            return _answer(["Cost", "Currency"], [[123.45, "USD"]]), None, None
        return None, "error", None

    monkeypatch.setattr(costs_module, "_bearer_token", lambda: "token")
    monkeypatch.setattr(costs_module, "_cost_post", _post)
    block = costs_module._query_billing()

    assert block["configured"] is True
    assert block["actual_month_to_date_usd"] == 123.45
    assert block["forecast_month_usd"] is None
    assert block["forecast_unavailable_reason"] == "error"
    assert any(p.endswith("/query") for p in calls)
    assert any(p.endswith("/forecast") for p in calls)


def test_reports_the_currency_azure_answered_with(monkeypatch):
    # A subscription billed in EUR must not have its total relabelled as dollars by a hardcoded
    # currency string.
    monkeypatch.setattr(costs_module, "_bearer_token", lambda: "token")
    monkeypatch.setattr(
        costs_module, "_cost_post",
        lambda path, body, token: (_answer(["Cost", "Currency"], [[9.0, "EUR"]]), None, None))
    assert costs_module._query_billing()["currency"] == "EUR"


# -- never live, and never hammered ------------------------------------------------------------

def test_the_label_never_claims_the_figure_is_live(monkeypatch):
    monkeypatch.setattr(costs_module, "_bearer_token", lambda: "token")
    monkeypatch.setattr(
        costs_module, "_cost_post",
        lambda path, body, token: (_answer(["Cost", "Currency"], [[1.0, "USD"]]), None, None))
    block = costs_module._query_billing()
    assert "live" not in block["freshness_label"].lower()
    assert "last updated" in block["freshness_label"].lower()
    # And it carries the four-hour caveat, so nobody reads month-to-date as current.
    assert "four hours" in block["refresh_note"]
    assert block["updated_at"]


def test_holds_the_answer_rather_than_querying_on_every_poll(monkeypatch):
    """The cost panel polls this endpoint every 60 SECONDS.

    Microsoft advises against querying Cost Management more than daily and rate-limits hard, so a
    per-request query would spend the subscription's quota on a panel nobody is reading.
    """
    calls = []
    monkeypatch.setattr(costs_module, "_AZ_SUB", "sub-1")
    monkeypatch.setattr(costs_module, "_query_billing",
                        lambda: calls.append(1) or {"configured": True, "unavailable_reason": None,
                                                    "actual_month_to_date_usd": 5.0})
    clock = [1000.0]
    for _ in range(50):
        costs_module.billing_block(now=lambda: clock[0])
        clock[0] += 60
    assert len(calls) == 1

    clock[0] += costs_module._BILLING_TTL_S
    costs_module.billing_block(now=lambda: clock[0])
    assert len(calls) == 2


def test_a_throttle_is_honoured_and_the_last_good_figure_is_kept(monkeypatch):
    # Serving the previous measurement through a 429 is more honest than replacing it with an
    # error: it carries its own updated_at, so the panel says how old the number is.
    monkeypatch.setattr(costs_module, "_AZ_SUB", "sub-1")
    good = {"configured": True, "unavailable_reason": None, "actual_month_to_date_usd": 7.5,
            "updated_at": "2026-09-06T12:00:00+00:00"}
    answers = [good, {"configured": False, "unavailable_reason": "throttled", "retry_after_s": 300.0}]
    calls = []

    def _query():
        calls.append(1)
        return answers[min(len(calls) - 1, len(answers) - 1)]

    monkeypatch.setattr(costs_module, "_query_billing", _query)
    clock = [1000.0]
    assert costs_module.billing_block(now=lambda: clock[0])["actual_month_to_date_usd"] == 7.5

    clock[0] += costs_module._BILLING_TTL_S + 1
    assert costs_module.billing_block(now=lambda: clock[0])["actual_month_to_date_usd"] == 7.5
    assert len(calls) == 2

    # Inside Retry-After the query is not repeated at all.
    clock[0] += 60
    costs_module.billing_block(now=lambda: clock[0])
    assert len(calls) == 2


def test_no_subscription_means_not_configured_and_no_call(monkeypatch):
    calls = []
    monkeypatch.setattr(costs_module, "_AZ_SUB", None)
    monkeypatch.setattr(costs_module, "_query_billing", lambda: calls.append(1) or {})
    block = costs_module.billing_block()
    assert block["configured"] is False
    assert block["unavailable_reason"] == "not_configured"
    assert calls == []


# -- the setup row and the tile must agree -----------------------------------------------------

def test_the_setup_row_is_derived_from_the_query_not_hardcoded(monkeypatch):
    """#1580 added a "Billing actuals" setup row that read "Azure Cost Management is not
    connected" unconditionally.

    That was true when it was written and is now a claim the code can check. If the row stayed
    hardcoded, the panel would say the feed is not connected directly above a real month-to-date
    figure read from it.
    """
    from fastapi.testclient import TestClient

    import routes.costs as served
    from api.app import app

    # `routes.costs`, NOT `api.routes.costs`. Both import paths resolve under this sys.path and
    # produce SEPARATE module objects; app.py binds the route to the former, so patching the
    # latter changes a module the request never reaches — and the assertion fails against a real
    # unconfigured answer rather than against the stub. tests/test_worker_capacity.py imports the
    # same way for the same reason.
    served._billing_cache.update({"at": 0.0, "value": None, "blocked_until": 0.0})
    monkeypatch.setattr(served, "_AZ_SUB", "sub-1")
    monkeypatch.setattr(served, "_app_names", lambda: ["acp-assess"])
    monkeypatch.setattr(served, "_az_client",
                        lambda: (_ for _ in ()).throw(RuntimeError("no azure here")))
    monkeypatch.setattr(served, "_query_billing", lambda: {
        "configured": True, "unavailable_reason": None, "actual_month_to_date_usd": 42.0,
        "forecast_month_usd": None, "currency": "USD", "updated_at": "2026-09-06T12:00:00+00:00",
        "freshness_label": "Azure billing data last updated",
        "refresh_note": served._BILLING_REFRESH_NOTE,
        "delay_note": served._BILLING_DELAY_NOTE,
    })

    body = TestClient(app).get("/control/costs").json()
    assert body["billing"]["actual_month_to_date_usd"] == 42.0
    assert body["setup"]["billing_actuals"]["configured"] is True
    assert body["setup"]["billing_actuals"]["reason"] is None


def test_an_unavailable_feed_gives_the_setup_row_the_tile_s_own_reason(monkeypatch):
    from fastapi.testclient import TestClient

    import routes.costs as served
    from api.app import app

    served._billing_cache.update({"at": 0.0, "value": None, "blocked_until": 0.0})
    monkeypatch.setattr(served, "_AZ_SUB", "sub-1")
    monkeypatch.setattr(served, "_app_names", lambda: ["acp-assess"])
    monkeypatch.setattr(served, "_az_client",
                        lambda: (_ for _ in ()).throw(RuntimeError("no azure here")))
    monkeypatch.setattr(served, "_query_billing", lambda: served._billing_unavailable(
        "permission", "Azure billing actuals unavailable: Cost Management Reader role needed"))

    body = TestClient(app).get("/control/costs").json()
    assert body["setup"]["billing_actuals"]["configured"] is False
    # The SAME string the tile shows, so the setup row and the tile cannot disagree about why.
    assert body["setup"]["billing_actuals"]["reason"] == body["billing"]["freshness_label"]
    assert "Cost Management Reader" in body["setup"]["billing_actuals"]["reason"]


def test_every_billing_shape_carries_the_delay_note(monkeypatch):
    # #1580's panel renders "Billing freshness: {delay_note}". A shape without the key blanks that
    # line, so the key is on the failure shapes too, not only on success.
    monkeypatch.setattr(costs_module, "_bearer_token", lambda: "token")
    monkeypatch.setattr(
        costs_module, "_cost_post",
        lambda path, body, token: (_answer(["Cost", "Currency"], [[1.0, "USD"]]), None, None))
    assert costs_module._query_billing()["delay_note"]
    assert costs_module._billing_unavailable("error", "nope")["delay_note"]


# -- a failure is not worth an hour ------------------------------------------------------------

def test_a_failure_is_retried_long_before_a_success_would_be(monkeypatch):
    """Observed 2026-09-06: the panel named a missing Cost Management Reader role, the role was
    granted, and the panel kept naming it — because the denial was cached for the same hour a
    real answer gets. The remedy was restarting the revision, which is a blunt fix for a cache
    this code chose.
    """
    calls = []
    monkeypatch.setattr(costs_module, "_AZ_SUB", "sub-1")
    answers = [costs_module._billing_unavailable("permission", "role needed"),
               {"configured": True, "unavailable_reason": None, "actual_month_to_date_usd": 12.0}]

    def _query():
        calls.append(1)
        return answers[min(len(calls) - 1, len(answers) - 1)]

    monkeypatch.setattr(costs_module, "_query_billing", _query)
    clock = [1000.0]
    assert costs_module.billing_block(now=lambda: clock[0])["configured"] is False
    assert len(calls) == 1

    # Inside the failure window it is held, so a broken deployment cannot re-query on every one
    # of the panel's 60-second polls.
    clock[0] += costs_module._BILLING_FAILURE_TTL_S - 1
    costs_module.billing_block(now=lambda: clock[0])
    assert len(calls) == 1

    # Past it — and long before the hour a SUCCESS would have been held for — it tries again and
    # picks up the granted role.
    clock[0] += 2
    assert costs_module.billing_block(now=lambda: clock[0])["actual_month_to_date_usd"] == 12.0
    assert len(calls) == 2
    assert costs_module._BILLING_FAILURE_TTL_S < costs_module._BILLING_TTL_S


def test_a_success_is_still_held_for_the_full_hour(monkeypatch):
    # The long TTL is the whole reason this cache exists: Cost Management rate-limits and the
    # panel polls every 60 seconds. Shortening the failure window must not shorten this one.
    calls = []
    monkeypatch.setattr(costs_module, "_AZ_SUB", "sub-1")
    monkeypatch.setattr(costs_module, "_query_billing",
                        lambda: calls.append(1) or {"configured": True, "unavailable_reason": None,
                                                    "actual_month_to_date_usd": 5.0})
    clock = [1000.0]
    costs_module.billing_block(now=lambda: clock[0])
    clock[0] += costs_module._BILLING_TTL_S - 1
    costs_module.billing_block(now=lambda: clock[0])
    assert len(calls) == 1

    clock[0] += 2
    costs_module.billing_block(now=lambda: clock[0])
    assert len(calls) == 2


def test_a_throttle_still_honours_retry_after_over_the_failure_window(monkeypatch):
    # Throttling has its own, longer hold — Retry-After is Azure telling us when to come back,
    # and the shorter failure window must not override it into re-querying sooner.
    monkeypatch.setattr(costs_module, "_AZ_SUB", "sub-1")
    calls = []
    monkeypatch.setattr(costs_module, "_query_billing",
                        lambda: calls.append(1) or {"configured": False,
                                                    "unavailable_reason": "throttled",
                                                    "retry_after_s": 900.0})
    clock = [1000.0]
    costs_module.billing_block(now=lambda: clock[0])
    assert len(calls) == 1

    clock[0] += costs_module._BILLING_FAILURE_TTL_S + 5
    costs_module.billing_block(now=lambda: clock[0])
    assert len(calls) == 1, "Retry-After must outrank the failure window"


# --- The setup row distinguishes "wait" from "fix it" ----------------------------------------------
# On 2026-09-07 the panel read "Billing actuals — Not configured" beside a tile saying "Cost
# Management is throttling". Same boolean, opposite operator actions.

def _served(monkeypatch, billing):
    import routes.costs as served
    served._billing_cache.update({"at": 0.0, "value": None, "blocked_until": 0.0})
    monkeypatch.setattr(served, "_AZ_SUB", "sub-1")
    monkeypatch.setattr(served, "_app_names", lambda: ["acp-assess"])
    monkeypatch.setattr(served, "_az_client",
                        lambda: (_ for _ in ()).throw(RuntimeError("no azure here")))
    monkeypatch.setattr(served, "_query_billing", lambda: billing)
    return served


def test_a_throttle_is_temporarily_unavailable_with_a_retry_time(monkeypatch):
    from datetime import datetime, timezone
    from fastapi.testclient import TestClient
    import routes.costs as served
    from api.app import app

    _served(monkeypatch, {
        **served._billing_unavailable(
            "throttled", "Azure billing actuals unavailable: Cost Management is throttling"),
        "retry_after_s": 900,
    })
    before = datetime.now(timezone.utc)
    row = TestClient(app).get("/control/costs").json()["setup"]["billing_actuals"]
    assert row["state"] == "throttled"
    assert row["configured"] is False, "the old boolean keeps its meaning: no figure came back"
    assert "throttling" in row["reason"]
    # Retry-After was 900s; the row names the wall-clock moment the hold lifts.
    retry_at = datetime.fromisoformat(row["retry_at"])
    assert 850 <= (retry_at - before).total_seconds() <= 950, row["retry_at"]


def test_a_denial_is_unavailable_and_a_missing_subscription_is_not_configured(monkeypatch):
    from fastapi.testclient import TestClient
    import routes.costs as served
    from api.app import app

    _served(monkeypatch, served._billing_unavailable(
        "permission", "Azure billing actuals unavailable: Cost Management Reader role needed"))
    row = TestClient(app).get("/control/costs").json()["setup"]["billing_actuals"]
    assert row["state"] == "unavailable"
    assert row["retry_at"] is None

    monkeypatch.setattr(served, "_AZ_SUB", None)
    row = TestClient(app).get("/control/costs").json()["setup"]["billing_actuals"]
    assert row["state"] == "not_configured"


def test_a_figure_is_connected_and_configured_stays_true(monkeypatch):
    from fastapi.testclient import TestClient
    import routes.costs as served
    from api.app import app

    _served(monkeypatch, {
        "configured": True, "unavailable_reason": None, "actual_month_to_date_usd": 42.0,
        "forecast_month_usd": None, "currency": "USD", "updated_at": "2026-09-07T12:00:00+00:00",
        "freshness_label": "Azure billing data last updated",
        "refresh_note": served._BILLING_REFRESH_NOTE, "delay_note": served._BILLING_DELAY_NOTE,
    })
    row = TestClient(app).get("/control/costs").json()["setup"]["billing_actuals"]
    assert (row["state"], row["configured"], row["reason"]) == ("connected", True, None)
