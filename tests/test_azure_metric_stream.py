"""Every Azure Monitor data point Live Operations can honestly show, and how it reaches the page.

Two claims are under test and neither is about Azure being up:

  1. A metric ACP asked for and did not get is REPORTED AS UNAVAILABLE, with its own name, rather
     than dropped from the payload or filled with a zero. "Nothing is happening" and "nobody
     measured" are different answers and the UI has to be able to tell them apart.

  2. The reading is taken once and SHARED. One Azure Monitor call per open Live Operations tab
     every two seconds is both slow on the critical path of an SSE frame and a good way to meet
     the metrics API's rate limit — and since these are PT1M metrics, it could not return
     anything new anyway.

Same caveat this file inherits from test_worker_capacity.py: the fake SDK response shapes are
built from published documentation, not exercised against a live Azure account. These prove the
endpoint's parsing and degradation given that shape; the first real deployment proves the shape.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

import pytest

NOW = datetime(2026, 9, 4, 14, 30, tzinfo=timezone.utc)


def _skip_pacing(monkeypatch):
    """The stream paces itself with asyncio.sleep(2), so six iterations is twelve seconds of
    waiting for assertions that take none. `admin_activity_stream` imports asyncio inside the
    function, so the patch goes on the asyncio module itself — safe here because nothing else in
    this call path (asyncio.run, asyncio.to_thread) goes through sleep."""
    import asyncio

    async def _no_sleep(_seconds):
        return None

    monkeypatch.setattr(asyncio, "sleep", _no_sleep)


def _point(value_attr, value, minute=None):
    stamp = None if minute is None else NOW.replace(minute=minute).isoformat()
    return SimpleNamespace(**{value_attr: value, "time_stamp": stamp})


def _metric(name, value_attr, points):
    return SimpleNamespace(name=SimpleNamespace(value=name),
                           timeseries=[SimpleNamespace(data=points)])


@pytest.fixture()
def control(monkeypatch):
    import routes.control as control_module
    monkeypatch.setattr(control_module, "_AZ_CONFIGURED", True)
    control_module._capacity_cache.update(at=0.0, value=None)
    return control_module


def _monitor(by_aggregation):
    """A fake Azure Monitor that answers per aggregation, the way the real API does — one
    aggregation per call, whatever names were asked for."""
    calls = []

    def _list(app_id, metricnames=None, aggregation=None, timespan=None, interval=None):
        calls.append({"names": (metricnames or "").split(","), "aggregation": aggregation,
                      "timespan": timespan, "interval": interval})
        return SimpleNamespace(value=by_aggregation.get(aggregation, []))

    return SimpleNamespace(metrics=SimpleNamespace(list=_list)), calls


def test_asks_azure_for_every_documented_metric_it_can_use(control):
    """The REST names are Microsoft's, not remembered ones: a wrong name is not an error, Azure
    simply answers nothing for it, which is indistinguishable from a metric with no data."""
    names = {rest for rest, *_ in control._AZ_METRICS}
    assert names == {
        "CpuPercentage", "MemoryPercentage", "Replicas", "UsageNanoCores", "WorkingSetBytes",
        "ResponseTime", "TotalCoresQuotaUsed", "RestartCount", "Requests", "RxBytes", "TxBytes",
        "ResiliencyRequestRetries", "ResiliencyConnectTimeouts", "ResiliencyEjectedHosts",
    }
    # Every aggregation asked for must be one the data point actually carries.
    assert {agg for _, _, agg, *_ in control._AZ_METRICS} <= {"Average", "Total", "Maximum"}


def test_groups_the_call_by_aggregation_rather_than_one_call_per_metric(control, monkeypatch):
    monitor, calls = _monitor({})
    monkeypatch.setattr(control, "_monitor_client", lambda: monitor)
    control._gather_metrics("/subs/x/app", NOW)
    # metrics.list takes many names but ONE aggregation, so three calls cover fourteen metrics.
    assert len(calls) == 3
    assert {call["aggregation"] for call in calls} == {"Average", "Total", "Maximum"}
    assert all(call["interval"] == "PT1M" for call in calls)
    assert sum(len(call["names"]) for call in calls) == len(control._AZ_METRICS)


def test_returns_the_per_minute_series_not_just_one_average(control, monkeypatch):
    """The old call collapsed five minutes to a single number and threw the shape away. The strip
    plots fifteen real minutes of Azure's own history, which is more than this browser saw."""
    monitor, _ = _monitor({"Average": [
        _metric("CpuPercentage", "average", [_point("average", 10.0, 20), _point("average", 30.0, 21)]),
    ]})
    monkeypatch.setattr(control, "_monitor_client", lambda: monitor)
    metrics, reason = control._gather_metrics("/subs/x/app", NOW)
    cpu = metrics["cpu_percent"]
    assert cpu["available"] is True
    assert [p["value"] for p in cpu["series"]] == [10.0, 30.0]
    assert cpu["latest"] == 30.0            # the newest reading, for "what is it right now"
    assert cpu["average"] == 20.0           # the window mean, which is what cpu_percent has always been
    assert cpu["azure_metric"] == "CpuPercentage"
    assert reason is None


def test_scales_nano_cores_into_cores(control, monkeypatch):
    monitor, _ = _monitor({"Average": [
        _metric("UsageNanoCores", "average", [_point("average", 1_500_000_000, 20)]),
    ]})
    monkeypatch.setattr(control, "_monitor_client", lambda: monitor)
    metrics, _ = control._gather_metrics("/subs/x/app", NOW)
    assert metrics["cpu_cores_used"]["latest"] == 1.5
    assert metrics["cpu_cores_used"]["unit"] == " cores"


def test_reads_each_aggregation_from_its_own_data_point_attribute(control, monkeypatch):
    """Total metrics carry `dp.total`, not `dp.average`. Reading the wrong attribute returns None
    for every point, which would present a busy app as one that has never restarted."""
    monitor, _ = _monitor({"Total": [
        _metric("RestartCount", "total", [_point("total", 2, 20), _point("total", 1, 21)]),
    ]})
    monkeypatch.setattr(control, "_monitor_client", lambda: monitor)
    metrics, _ = control._gather_metrics("/subs/x/app", NOW)
    assert metrics["restarts"]["available"] is True
    assert metrics["restarts"]["latest"] == 1.0


def test_a_metric_azure_does_not_answer_for_is_named_as_unavailable(control, monkeypatch):
    monitor, _ = _monitor({"Average": [
        _metric("CpuPercentage", "average", [_point("average", 10.0, 20)]),
    ]})
    monkeypatch.setattr(control, "_monitor_client", lambda: monitor)
    metrics, _ = control._gather_metrics("/subs/x/app", NOW)
    # Present, named, and honest — not absent, and above all not zero.
    assert metrics["requests"]["available"] is False
    assert metrics["requests"]["latest"] is None
    assert metrics["requests"]["series"] == []
    assert metrics["requests"]["label"] == "Requests"
    assert set(metrics) == {key for _, key, *_ in control._AZ_METRICS}


def test_a_gap_in_the_series_is_dropped_rather_than_carried_as_zero(control, monkeypatch):
    monitor, _ = _monitor({"Average": [
        _metric("CpuPercentage", "average",
                [_point("average", 10.0, 20), _point("average", None, 21), _point("average", 12.0, 22)]),
    ]})
    monkeypatch.setattr(control, "_monitor_client", lambda: monitor)
    metrics, _ = control._gather_metrics("/subs/x/app", NOW)
    assert [p["value"] for p in metrics["cpu_percent"]["series"]] == [10.0, 12.0]
    assert metrics["cpu_percent"]["average"] == 11.0   # the gap is not a zero dragging the mean down


def test_a_point_with_no_timestamp_counts_but_is_not_plotted(control, monkeypatch):
    """Something has to place a point on a time axis and nothing here may invent that."""
    monitor, _ = _monitor({"Average": [
        _metric("CpuPercentage", "average", [_point("average", 10.0), _point("average", 20.0, 21)]),
    ]})
    monkeypatch.setattr(control, "_monitor_client", lambda: monitor)
    metrics, _ = control._gather_metrics("/subs/x/app", NOW)
    assert metrics["cpu_percent"]["average"] == 15.0
    assert [p["value"] for p in metrics["cpu_percent"]["series"]] == [20.0]


def test_a_group_that_fails_degrades_only_its_own_metrics(control, monkeypatch):
    def _list(app_id, metricnames=None, aggregation=None, **kw):
        if aggregation == "Total":
            raise RuntimeError("transient")
        return SimpleNamespace(value=[_metric("CpuPercentage", "average", [_point("average", 9.0, 20)])])

    monkeypatch.setattr(control, "_monitor_client",
                        lambda: SimpleNamespace(metrics=SimpleNamespace(list=_list)))
    metrics, reason = control._gather_metrics("/subs/x/app", NOW)
    assert metrics["cpu_percent"]["available"] is True
    assert metrics["restarts"]["available"] is False
    assert reason == "error"


def test_a_permission_failure_says_so_rather_than_error(control, monkeypatch):
    def _list(*a, **kw):
        raise type("HttpResponseError", (RuntimeError,), {"status_code": 403})("forbidden")

    monkeypatch.setattr(control, "_monitor_client",
                        lambda: SimpleNamespace(metrics=SimpleNamespace(list=_list)))
    _metrics, reason = control._gather_metrics("/subs/x/app", NOW)
    assert reason == "permission"


def test_calls_that_succeed_with_nothing_are_no_data_not_an_error(control, monkeypatch):
    monitor, _ = _monitor({})
    monkeypatch.setattr(control, "_monitor_client", lambda: monitor)
    _metrics, reason = control._gather_metrics("/subs/x/app", NOW)
    assert reason == "no_data"


def test_a_name_from_another_aggregation_group_is_ignored(control, monkeypatch):
    """A fake — or a real Azure — that answers with a name this group did not request must not be
    mapped onto whichever key happens to share it. Reading a Total metric's points with `.average`
    would silently produce an empty series that looks like "no data"."""
    monitor, _ = _monitor({"Average": [
        _metric("RestartCount", "average", [_point("average", 99.0, 20)]),
    ]})
    monkeypatch.setattr(control, "_monitor_client", lambda: monitor)
    metrics, _ = control._gather_metrics("/subs/x/app", NOW)
    assert metrics["restarts"]["available"] is False


# ── The reading is taken once and shared ────────────────────────────────────────────────────

def test_one_azure_read_serves_every_open_tab(control, monkeypatch):
    calls = []
    monkeypatch.setattr(control, "get_capacity", lambda: (calls.append(1), {"measured_at": "t0"})[1])
    first = control.cached_capacity()
    for _ in range(20):
        control.cached_capacity()
    assert calls == [1]
    assert first == {"measured_at": "t0"}


def test_the_reading_refreshes_once_the_ttl_has_passed(control, monkeypatch):
    calls = []
    monkeypatch.setattr(control, "get_capacity",
                        lambda: (calls.append(1), {"measured_at": f"t{len(calls)}"})[1])
    control.cached_capacity(ttl_s=60)
    assert control.cached_capacity(ttl_s=60)["measured_at"] == "t1"
    # A zero TTL is "always stale", which is how a caller forces a fresh reading.
    assert control.cached_capacity(ttl_s=0)["measured_at"] == "t2"
    assert len(calls) == 2


def test_a_failed_refresh_keeps_the_last_good_reading(control, monkeypatch):
    """Replacing a real measurement with an empty one on a transient Azure fault is the specific
    failure that would make the panel flicker between measured and "not reported"."""
    monkeypatch.setattr(control, "get_capacity", lambda: {"measured_at": "good"})
    assert control.cached_capacity(ttl_s=60)["measured_at"] == "good"
    monkeypatch.setattr(control, "get_capacity",
                        lambda: (_ for _ in ()).throw(RuntimeError("azure is down")))
    assert control.cached_capacity(ttl_s=0)["measured_at"] == "good"


def test_a_first_read_that_fails_is_none_not_an_empty_reading(control, monkeypatch):
    monkeypatch.setattr(control, "get_capacity",
                        lambda: (_ for _ in ()).throw(RuntimeError("azure is down")))
    assert control.cached_capacity(ttl_s=0) is None


# ── How it reaches the page ─────────────────────────────────────────────────────────────────

def _frames(chunks):
    """Parse an SSE byte/str stream into [(event, data)] pairs, ignoring keep-alive comments."""
    import json as _json
    out = []
    for chunk in chunks:
        text = chunk.decode() if isinstance(chunk, bytes) else chunk
        if text.startswith(":"):
            continue
        event, _, rest = text.partition("\n")
        payload = rest.split("data: ", 1)[1].strip() if "data: " in rest else "{}"
        out.append((event.replace("event: ", ""), _json.loads(payload)))
    return out


def _run(system_module, request, limit):
    """Drive the SSE generator to `limit` frames. asyncio.run rather than a pytest-asyncio
    marker: this suite has no async plugin, and the route is a plain coroutine."""
    import asyncio

    async def _go():
        response = await system_module.admin_activity_stream(request)
        chunks = []
        async for chunk in response.body_iterator:
            chunks.append(chunk)
            if len(chunks) >= limit:
                break
        return _frames(chunks)

    return asyncio.run(_go())


class _StreamRequest:
    """Disconnects after `ticks` loop iterations, so the generator terminates in a test."""

    def __init__(self, ticks=6):
        self.state = SimpleNamespace(user_email="viewer@example.org")
        self._left = ticks

    async def is_disconnected(self):
        self._left -= 1
        return self._left < 0


def test_azure_rides_its_own_sse_event_rather_than_every_activity_frame(monkeypatch):
    """Fourteen metrics each carrying a fifteen-minute series is a large payload next to a job
    tally that changes several times a minute. Attaching it to every activity frame would multiply
    the stream's size for data that had not changed."""
    from api.routes import system as system_module

    snapshots = iter([{"runs": [], "summary": {"queued": n}} for n in range(10)])
    monkeypatch.setattr(system_module, "_admin_activity_snapshot", lambda: next(snapshots))
    monkeypatch.setattr(system_module, "_azure_block", lambda: {"measured_at": "t0", "configured": True})
    _skip_pacing(monkeypatch)

    frames = _run(system_module, _StreamRequest(3), 6)
    events = [event for event, _ in frames]
    # The activity frame fires on every change; the Azure frame fires once, because the reading
    # was taken once.
    assert events.count("azure") == 1
    assert events.count("activity") >= 2
    assert all("azure" not in payload for event, payload in frames if event == "activity")


def test_a_re_measured_reading_is_sent_even_when_its_values_are_unchanged(monkeypatch):
    """Gating on the VALUES would leave the page showing "Azure Monitor · 4m ago" for a figure
    that had just been re-measured — understating freshness, which is the direction that misleads.
    So the trigger is measured_at moving, not the numbers moving."""
    from api.routes import system as system_module

    monkeypatch.setattr(system_module, "_admin_activity_snapshot", lambda: {"runs": [], "summary": {}})
    stamps = iter(["t0", "t0", "t1", "t1", "t2", "t2", "t3"])
    monkeypatch.setattr(system_module, "_azure_block",
                        lambda: {"measured_at": next(stamps), "cpu_percent": 40})
    _skip_pacing(monkeypatch)

    frames = _run(system_module, _StreamRequest(6), 8)
    sent = [payload["measured_at"] for event, payload in frames if event == "azure"]
    assert sent == ["t0", "t1", "t2"]


def test_an_azure_read_that_fails_does_not_interrupt_the_activity_stream(monkeypatch):
    from api.routes import system as system_module

    snapshots = iter([{"runs": [], "summary": {"queued": n}} for n in range(10)])
    monkeypatch.setattr(system_module, "_admin_activity_snapshot", lambda: next(snapshots))
    monkeypatch.setattr(system_module, "_azure_block", lambda: None)
    _skip_pacing(monkeypatch)

    frames = _run(system_module, _StreamRequest(3), 4)
    assert [event for event, _ in frames].count("azure") == 0
    assert [event for event, _ in frames].count("activity") >= 2


# ── Requests by response class ──────────────────────────────────────────────────────────────

def _split_series(label, totals, style="mgmt"):
    """A dimension-split time series in either of the two shapes the Azure packages document."""
    data = [SimpleNamespace(total=value, time_stamp=NOW.replace(minute=20 + i).isoformat())
            for i, value in enumerate(totals)]
    if style == "mgmt":
        return SimpleNamespace(data=data, metadatavalues=[
            SimpleNamespace(name=SimpleNamespace(value="statuscodecategory"), value=label)])
    return SimpleNamespace(data=data, metadata_values={"statuscodecategory": label})


def _split_client(series_list, capture=None):
    def _list(app_id, metricnames=None, aggregation=None, timespan=None, interval=None, filter=None):
        if capture is not None:
            capture.append({"names": metricnames, "aggregation": aggregation, "filter": filter})
        return SimpleNamespace(value=[SimpleNamespace(
            name=SimpleNamespace(value="Requests"), timeseries=series_list)])
    return SimpleNamespace(metrics=SimpleNamespace(list=_list))


def test_requests_are_split_by_response_class_with_one_filtered_call(control, monkeypatch):
    """statusCodeCategory is a DIMENSION on Requests, not three separate metrics, so this is one
    call with a filter rather than three more names in _AZ_METRICS."""
    calls = []
    monkeypatch.setattr(control, "_monitor_client", lambda: _split_client([
        _split_series("2xx", [10, 12]), _split_series("5xx", [1, 0])], calls))
    split = control._status_split("/subs/x/app", NOW)
    assert split == {"2xx": 22.0, "5xx": 1.0}
    assert len(calls) == 1
    assert calls[0]["filter"] == "statusCodeCategory eq '*'"
    assert calls[0]["names"] == "Requests"


def test_the_dimension_is_read_from_either_documented_shape(control, monkeypatch):
    """azure-mgmt-monitor documents `metadatavalues` as a list of MetadataValue; the newer
    azure-monitor-query documents `metadata_values` as a dict. Trying both avoids a shape mismatch
    becoming a silently unsplit metric."""
    monkeypatch.setattr(control, "_monitor_client",
                        lambda: _split_client([_split_series("4xx", [3], style="query")]))
    assert control._status_split("/subs/x/app", NOW) == {"4xx": 3.0}


def test_a_response_class_azure_did_not_report_is_absent_not_zero(control, monkeypatch):
    """An app serving no 5xx and an app whose metrics have not arrived must not render alike."""
    monkeypatch.setattr(control, "_monitor_client",
                        lambda: _split_client([_split_series("2xx", [10])]))
    split = control._status_split("/subs/x/app", NOW)
    assert "5xx" not in split and "4xx" not in split
    # A series with no data points at all contributes nothing rather than a zero.
    monkeypatch.setattr(control, "_monitor_client",
                        lambda: _split_client([_split_series("2xx", [None, None])]))
    assert control._status_split("/subs/x/app", NOW) == {}


def test_an_unrecognised_dimension_value_is_ignored(control, monkeypatch):
    monkeypatch.setattr(control, "_monitor_client",
                        lambda: _split_client([_split_series("teapot", [7])]))
    assert control._status_split("/subs/x/app", NOW) == {}


def test_a_failed_split_leaves_the_unsplit_request_total_intact(control, monkeypatch):
    monkeypatch.setattr(control, "_monitor_client", lambda: SimpleNamespace(
        metrics=SimpleNamespace(list=lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("no dims")))))
    assert control._status_split("/subs/x/app", NOW) == {}
