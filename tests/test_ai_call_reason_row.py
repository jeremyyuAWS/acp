"""The failure reason has to survive the trip to the ai_calls row.

A reason the adapter computes but nobody persists is worth exactly as much as the bare
`except Exception` it replaced: the operator still has to reproduce the call by hand to learn
anything. So the row records WHICH way a vision call failed, and the governance rollup breaks
`failed` down by it — because `failed: 12` is a number that says something is wrong and nothing
about what.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

import providers  # noqa: E402


@pytest.fixture()
def rows(isolated_store, monkeypatch):
    """Point ai._trace_ai's provenance write at an isolated store and read the rows back."""
    import core
    monkeypatch.setattr(core, "store", isolated_store)
    return lambda: isolated_store.list_ai_calls()


def _fake_provider(result: dict):
    """A provider stub returning one canned result — this suite is about what ai.py does with a
    result, not about the transport (test_vision_failure_reason.py covers that)."""
    return types.SimpleNamespace(
        name=result.get("provider", "ollama"),
        generate=lambda prompt, image_bytes, model=None, timeout=None: result,
    )


def _res(**kw):
    base = {"text": None, "model": "moondream", "provider": "ollama", "zone": "local",
            "latency_ms": 12, "ok": False, "cost_usd": 0.0}
    base.update(kw)
    return base


@pytest.mark.parametrize("reason", [
    providers.REASON_TRANSPORT,
    "http_404",
    providers.REASON_EMPTY,
])
def test_each_failure_reason_lands_on_the_row(monkeypatch, rows, reason):
    import ai
    monkeypatch.setattr(providers, "active_vision_provider",
                        lambda: _fake_provider(_res(reason=reason)))
    assert ai._vision_generate("describe", b"IMG") is None
    row = rows()[0]
    assert row["ok"] == 0
    assert row["reason"] == reason


def test_a_successful_call_is_recorded_as_ok(monkeypatch, rows):
    import ai
    monkeypatch.setattr(providers, "active_vision_provider",
                        lambda: _fake_provider(_res(text="A bar chart of Q4 revenue", ok=True,
                                                    reason=providers.REASON_OK)))
    assert ai._vision_generate("describe", b"IMG") == "A bar chart of Q4 revenue"
    row = rows()[0]
    assert row["ok"] == 1 and row["reason"] == providers.REASON_OK


def test_a_reply_the_guard_rejects_is_not_reported_as_a_dead_endpoint(monkeypatch, rows, capsys):
    """The fourth way to end at None, and the only one where the transport was fine. Reported as
    a plain ok=0 it points the next operator at Ollama for a problem that is in the reply."""
    import ai
    monkeypatch.setattr(providers, "active_vision_provider",
                        lambda: _fake_provider(_res(text="Chart", ok=True,
                                                    reason=providers.REASON_OK)))
    assert ai._vision_generate("describe", b"IMG") is None       # one word — fails 1.1.1
    row = rows()[0]
    assert row["ok"] == 0
    assert row["reason"] == providers.REASON_UNUSABLE
    assert row["reason"] != providers.REASON_TRANSPORT
    assert "rejected by the alt-text guard" in capsys.readouterr().out


def test_a_provider_that_omits_a_reason_still_records_one(monkeypatch, rows):
    """Defensive: a third-party adapter predating the field must not write a NULL that reads as
    'nobody looked' when what happened is 'the adapter did not say'."""
    import ai
    res = _res()
    res.pop("reason", None)
    monkeypatch.setattr(providers, "active_vision_provider", lambda: _fake_provider(res))
    assert ai._vision_generate("describe", b"IMG") is None
    assert rows()[0]["reason"] == providers.REASON_TRANSPORT


def test_escalation_records_the_cloud_providers_reason(monkeypatch, rows):
    """The escalation path traces a provider result directly rather than through
    _vision_generate, so it is a second place the reason can be dropped."""
    import ai
    monkeypatch.setattr(providers, "cloud_vision_provider",
                        lambda: _fake_provider(_res(provider="azure_openai", zone="tenant",
                                                    model="gpt-4o", reason="http_401")))
    assert ai._escalate_vision("describe", b"IMG") is None
    row = rows()[0]
    assert row["provider"] == "azure_openai" and row["reason"] == "http_401"


# ── The rollup makes `failed` actionable ───────────────────────────────────────

def test_rollup_breaks_failures_down_by_reason(isolated_store):
    s = isolated_store

    def rec(ok, reason):
        s.record_ai_call(surface="vision", provider="ollama", model="moondream", zone="local",
                         latency_ms=100, ok=ok, reason=reason)

    rec(True, providers.REASON_OK)
    rec(False, providers.REASON_EMPTY)
    rec(False, providers.REASON_EMPTY)
    rec(False, providers.REASON_TRANSPORT)
    rec(False, "http_404")

    r = s.ai_cost_rollup(since_days=None)
    assert r["failed"] == 4
    by_reason = {g["key"]: g["calls"] for g in r["failure_reasons"]}
    assert by_reason == {providers.REASON_EMPTY: 2, providers.REASON_TRANSPORT: 1, "http_404": 1}
    assert providers.REASON_OK not in by_reason          # successes are not failures


def test_rollup_reason_breakdown_respects_the_scan_scope(isolated_store):
    s = isolated_store
    for scan, reason in (("s1", providers.REASON_EMPTY), ("s2", providers.REASON_TRANSPORT)):
        s.record_ai_call(surface="vision", provider="ollama", model="m", zone="local",
                         latency_ms=1, ok=False, reason=reason, scan_id=scan)
    r = s.ai_cost_rollup(since_days=None, scan_id="s1")
    assert [g["key"] for g in r["failure_reasons"]] == [providers.REASON_EMPTY]


def test_rows_written_before_the_column_existed_say_so(isolated_store):
    """Pre-migration rows have a NULL reason. That is 'nobody recorded it', which is a different
    statement from any of the reasons — so it must not be silently folded into one of them."""
    s = isolated_store
    with s._db.cursor() as cur:
        s._db.execute(cur,
            "INSERT INTO ai_calls(id,ts,scan_id,file,surface,provider,model,zone,latency_ms,ok,cost_usd) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            ("legacy1", "2026-07-30T00:00:00+00:00", None, None, "vision", "ollama", "moondream",
             "local", 200, 0, 0.0))
    r = s.ai_cost_rollup(since_days=None)
    assert [g["key"] for g in r["failure_reasons"]] == ["unrecorded"]
