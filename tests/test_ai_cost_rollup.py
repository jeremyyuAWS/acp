"""AI cost/usage governance rollup (ADR 0019 Phase 1).

Every figure is a real aggregate of recorded ai_calls — never a fabricated estimate
(ADR 0016). For the keyless local build cost is a genuine $0; a cloud adapter's real
per-call cost sums through unchanged. Windowing (today / month / all-time) is by ts.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))


def _record(store, **kw):
    store.record_ai_call(surface=kw.get("surface", "vision"),
                         provider=kw.get("provider", "ollama"),
                         model=kw.get("model", "llava:13b"),
                         zone=kw.get("zone", "local"),
                         latency_ms=kw.get("latency_ms", 400),
                         ok=kw.get("ok", True),
                         cost_usd=kw.get("cost_usd", 0.0),
                         scan_id=kw.get("scan_id"))


def test_rollup_aggregates_calls_success_latency_and_cost(isolated_store):
    s = isolated_store
    _record(s, surface="vision", ok=True, latency_ms=300, cost_usd=0.0)
    _record(s, surface="vision", ok=True, latency_ms=500, cost_usd=0.0)
    _record(s, surface="explain", ok=False, latency_ms=100, cost_usd=0.0)
    r = s.ai_cost_rollup(since_days=None)
    assert r["calls"] == 3 and r["ok"] == 2 and r["failed"] == 1
    assert r["cost_usd"] == 0.0                      # local build — genuine zero
    assert r["avg_latency_ms"] == 300                # (300+500+100)/3
    by_surface = {g["key"]: g["calls"] for g in r["by_surface"]}
    assert by_surface == {"vision": 2, "explain": 1}


def test_cloud_cost_sums_through_and_zones_split(isolated_store):
    s = isolated_store
    _record(s, provider="ollama", zone="local", cost_usd=0.0)
    _record(s, provider="openai", zone="cloud", cost_usd=0.012)
    _record(s, provider="openai", zone="cloud", cost_usd=0.008)
    r = s.ai_cost_rollup(since_days=None)
    assert r["cost_usd"] == 0.02
    by_zone = {g["key"]: g["cost_usd"] for g in r["by_zone"]}
    assert by_zone["cloud"] == 0.02 and by_zone["local"] == 0.0


def test_window_excludes_older_calls(isolated_store):
    s = isolated_store
    # one fresh row + one row 40 days old (write ts directly for the age)
    _record(s)
    old_ts = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
    with s._db.cursor() as cur:
        s._db.execute(cur,
            "INSERT INTO ai_calls(id,ts,scan_id,file,surface,provider,model,zone,latency_ms,ok,cost_usd) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            ("old1", old_ts, None, None, "vision", "ollama", "m", "local", 200, 1, 0.0))
    assert s.ai_cost_rollup(since_days=30)["calls"] == 1     # the 40-day-old one is excluded
    assert s.ai_cost_rollup(since_days=None)["calls"] == 2   # all-time sees both


def test_empty_rollup_is_all_zeros_not_an_error(isolated_store):
    r = isolated_store.ai_cost_rollup(since_days=1)
    assert r["calls"] == 0 and r["cost_usd"] == 0.0 and r["avg_latency_ms"] == 0
    assert r["by_provider"] == [] and r["by_zone"] == []


def test_costs_endpoint_returns_three_windows():
    src = (Path(__file__).resolve().parent.parent / "api" / "routes" / "ai.py").read_text()
    assert '@router.get("/ai/costs")' in src
    assert 'core.store.ai_cost_rollup(since_days=1)' in src
    assert 'core.store.ai_cost_rollup(since_days=30)' in src
    assert 'core.store.ai_cost_rollup(since_days=None)' in src
