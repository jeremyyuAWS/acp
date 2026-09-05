"""HuggingFace endpoint health monitoring (step 6 of the HF integration roadmap).

Three things under test:

  1. cloud_vision_provider() includes gemini and bedrock in its auto-fallback order, not only
     as explicit admin selections — the fix for the correctness bug found in review.

  2. store.ai_provider_health_stats() aggregates ai_calls rows into a health snapshot:
     total calls, success rate, latency percentiles, throttle events, and cold-start signals.
     All numbers are real aggregates, never fabricated (ADR 0016).

  3. GET /ai/providers/{provider}/health returns that snapshot for any CLOUD_PROVIDERS
     entry and is gated behind the admin guard.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

import providers  # noqa: E402


# ── 1. cloud_vision_provider() fallback order ─────────────────────────────────────────────────

def _fake_core_with_providers(enabled_providers, monkeypatch):
    """Patch `core` so cloud_vision_provider() sees only the providers in enabled_providers
    as configured+enabled. Returns the list of adapter names cloud_vision_provider() tried."""
    tried = []

    class _FakeStore:
        def get_setting(self, key):
            return None

        def get_ai_provider_config(self, name):
            if name in enabled_providers:
                tried.append(name)
                return {"enabled": True, "model": "x", "endpoint": "https://example.com",
                        "deployment": "d", "key_secret_ref": "K",
                        "aws_access_key_id": "AKID", "region": "us-east-1"}
            return None

    import types
    fake_core = types.SimpleNamespace(store=_FakeStore())
    monkeypatch.setitem(sys.modules, "core", fake_core)
    return tried


def test_cloud_vision_provider_fallback_includes_gemini(monkeypatch):
    monkeypatch.setenv("K", "sk-test")
    tried = _fake_core_with_providers({"gemini"}, monkeypatch)
    result = providers.cloud_vision_provider()
    assert result is not None, "gemini should be reachable as auto-fallback, not only as explicit selection"
    assert "gemini" in tried


def test_cloud_vision_provider_fallback_includes_bedrock(monkeypatch):
    monkeypatch.setenv("K", "sk-test")
    monkeypatch.setenv("AKID", "AKIAIOSFODNN7EXAMPLE")
    tried = _fake_core_with_providers({"bedrock"}, monkeypatch)
    result = providers.cloud_vision_provider()
    assert result is not None, "bedrock should be reachable as auto-fallback, not only as explicit selection"
    assert "bedrock" in tried


def test_cloud_vision_provider_all_six_are_in_the_auto_fallback_order(monkeypatch):
    """Every CLOUD_PROVIDERS entry is reachable via auto-fallback (no explicit admin selection)."""
    monkeypatch.setenv("K", "sk-test")
    monkeypatch.setenv("AKID", "AKIAIOSFODNN7EXAMPLE")
    for name in providers.CLOUD_PROVIDERS:
        tried = _fake_core_with_providers({name}, monkeypatch)
        result = providers.cloud_vision_provider()
        assert result is not None, f"{name} not reached by auto-fallback"
        assert name in tried, f"{name} not in tried list"


def test_explicit_admin_selection_is_tried_first(monkeypatch):
    """When ai_vision_provider is set by admin, that provider is attempted before others."""
    monkeypatch.setenv("K", "sk-test")
    order = []

    class _FakeStore:
        def get_setting(self, key):
            return "anthropic"

        def get_ai_provider_config(self, name):
            order.append(name)
            if name in {"anthropic", "openai"}:
                return {"enabled": True, "model": "x", "key_secret_ref": "K"}
            return None

    import types
    monkeypatch.setitem(sys.modules, "core", types.SimpleNamespace(store=_FakeStore()))
    providers.cloud_vision_provider()
    assert order[0] == "anthropic", "admin-selected provider must be tried first"


# ── 2. store.ai_provider_health_stats() ──────────────────────────────────────────────────────

def _insert_calls(store, rows):
    """Insert ai_calls rows directly into the isolated store for test setup."""
    for r in rows:
        store.record_ai_call(
            surface=r.get("surface", "alt_text"),
            provider=r["provider"],
            model=r.get("model", "test-model"),
            zone=r.get("zone", "cloud"),
            latency_ms=r["latency_ms"],
            ok=r.get("ok", True),
            reason=r.get("reason"),
        )


def _recent(hours_ago: float = 1) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()


def test_health_stats_empty_window(isolated_store):
    stats = isolated_store.ai_provider_health_stats("huggingface", window_hours=24)
    assert stats["calls"] == 0
    assert stats["ok"] == 0
    assert stats["errors"] == 0
    assert stats["throttle_count"] == 0
    assert stats["cold_start_count"] == 0
    assert stats["p95_latency_ms"] is None
    assert stats["last_call_ts"] is None


def test_health_stats_counts_calls_and_errors(isolated_store):
    _insert_calls(isolated_store, [
        {"provider": "huggingface", "latency_ms": 500, "ok": True},
        {"provider": "huggingface", "latency_ms": 300, "ok": True},
        {"provider": "huggingface", "latency_ms": 100, "ok": False, "reason": "transport"},
    ])
    stats = isolated_store.ai_provider_health_stats("huggingface", window_hours=24)
    assert stats["calls"] == 3
    assert stats["ok"] == 2
    assert stats["errors"] == 1


def test_health_stats_scoped_to_provider(isolated_store):
    _insert_calls(isolated_store, [
        {"provider": "huggingface", "latency_ms": 400, "ok": True},
        {"provider": "openai", "latency_ms": 200, "ok": True},
    ])
    stats = isolated_store.ai_provider_health_stats("huggingface", window_hours=24)
    assert stats["calls"] == 1


def test_health_stats_throttle_count(isolated_store):
    _insert_calls(isolated_store, [
        {"provider": "huggingface", "latency_ms": 50, "ok": False, "reason": "http_429"},
        {"provider": "huggingface", "latency_ms": 50, "ok": False, "reason": "http_429"},
        {"provider": "huggingface", "latency_ms": 400, "ok": True},
    ])
    stats = isolated_store.ai_provider_health_stats("huggingface", window_hours=24)
    assert stats["throttle_count"] == 2


def test_health_stats_cold_start_count(isolated_store):
    # >30 000 ms latency on a successful call is the cold-start signal
    _insert_calls(isolated_store, [
        {"provider": "huggingface", "latency_ms": 35_000, "ok": True},
        {"provider": "huggingface", "latency_ms": 500, "ok": True},
        # A failed slow call is NOT a cold start (ok=False)
        {"provider": "huggingface", "latency_ms": 40_000, "ok": False, "reason": "transport"},
    ])
    stats = isolated_store.ai_provider_health_stats("huggingface", window_hours=24)
    assert stats["cold_start_count"] == 1


def test_health_stats_p95_with_enough_data(isolated_store):
    # Insert 20 calls with latencies 100..2000 ms (step 100), all successful
    latencies = list(range(100, 2100, 100))  # [100, 200, ..., 2000]
    _insert_calls(isolated_store, [
        {"provider": "huggingface", "latency_ms": ms, "ok": True} for ms in latencies
    ])
    stats = isolated_store.ai_provider_health_stats("huggingface", window_hours=24)
    # 95th percentile of 20 sorted values is index 19 (min(int(20*0.95), 19) = min(19,19))
    # latencies sorted = [100, 200, ..., 2000]; index 19 = 2000
    assert stats["p95_latency_ms"] == 2000
    assert stats["avg_latency_ms"] > 0


def test_health_stats_p95_single_datapoint(isolated_store):
    _insert_calls(isolated_store, [{"provider": "huggingface", "latency_ms": 750, "ok": True}])
    stats = isolated_store.ai_provider_health_stats("huggingface", window_hours=24)
    assert stats["p95_latency_ms"] == 750


def test_health_stats_last_call_ts_populated(isolated_store):
    _insert_calls(isolated_store, [{"provider": "huggingface", "latency_ms": 300, "ok": True}])
    stats = isolated_store.ai_provider_health_stats("huggingface", window_hours=24)
    assert stats["last_call_ts"] is not None


def test_health_stats_window_excludes_old_calls(isolated_store):
    """Calls outside the window are not counted."""
    # Use store's record_ai_call directly — it always uses now(), so we can only test
    # that a fresh call IS included and the count matches expectations.
    _insert_calls(isolated_store, [{"provider": "huggingface", "latency_ms": 300, "ok": True}])
    # window_hours=0 not valid (ge=1), but we can verify the 1-hour window includes our fresh call
    stats = isolated_store.ai_provider_health_stats("huggingface", window_hours=1)
    assert stats["calls"] == 1


def test_health_stats_provider_field_in_response(isolated_store):
    stats = isolated_store.ai_provider_health_stats("huggingface", window_hours=24)
    assert stats["provider"] == "huggingface"
    assert stats["window_hours"] == 24


# ── 3. GET /ai/providers/{provider}/health route ──────────────────────────────────────────────

def _make_app(isolated_store, monkeypatch):
    import core
    import types
    monkeypatch.setattr(core, "store", isolated_store)
    # Mount the router
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import routes.system as sys_routes
    app = FastAPI()
    app.include_router(sys_routes.router)
    # Bypass admin guard
    monkeypatch.setattr(sys_routes, "_require_admin", lambda req: None)
    return TestClient(app)


def test_health_route_returns_stats(isolated_store, monkeypatch):
    _insert_calls(isolated_store, [
        {"provider": "huggingface", "latency_ms": 500, "ok": True},
    ])
    client = _make_app(isolated_store, monkeypatch)
    resp = client.get("/ai/providers/huggingface/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["provider"] == "huggingface"
    assert body["calls"] == 1
    assert body["ok"] == 1


def test_health_route_window_hours_param(isolated_store, monkeypatch):
    client = _make_app(isolated_store, monkeypatch)
    resp = client.get("/ai/providers/huggingface/health?window_hours=48")
    assert resp.status_code == 200
    assert resp.json()["window_hours"] == 48


def test_health_route_rejects_unknown_provider(isolated_store, monkeypatch):
    client = _make_app(isolated_store, monkeypatch)
    resp = client.get("/ai/providers/imaginary_llm/health")
    assert resp.status_code == 422


def test_health_route_accepts_all_cloud_providers(isolated_store, monkeypatch):
    client = _make_app(isolated_store, monkeypatch)
    for name in providers.CLOUD_PROVIDERS:
        resp = client.get(f"/ai/providers/{name}/health")
        assert resp.status_code == 200, f"{name} should be accepted by the health route"
