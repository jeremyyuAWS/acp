"""P1.4c — Fallback visibility: W2: warning + vision_fallback flag.

When _vision_generate silently degrades from a cloud provider to the local CPU
floor, two things must be observable:
  1. A W2: vision-fallback warning is emitted via logging.warning — visible in
     container logs and any log-aggregation pipeline.
  2. describe_image / describe_image_structured return vision_fallback=True in
     the draft dict so callers can surface "Enhanced cloud vision unavailable;
     output quality may be reduced" in the product or operational telemetry.

Without these signals, production can silently fall from a 3/6-accurate cloud
model to a 0/6-accurate local CPU model while still reporting success (P1.4c).
"""
import logging
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

import ai  # noqa: E402
import providers  # noqa: E402


# ── Helpers ────────────────────────────────────────────────────────────────────

def _cloud_prov(*, fail: bool):
    """Fake cloud provider (runpod_serverless) that either fails or returns usable text."""
    prov = MagicMock()
    prov.name = "runpod_serverless"
    if fail:
        prov.generate.return_value = {
            "ok": False, "text": None, "reason": providers.REASON_TRANSPORT,
            "provider": "runpod_serverless", "zone": "cloud", "cost_usd": 0.0,
            "model": "qwen2.5-vl", "latency_ms": 0,
            "prompt_tokens": None, "completion_tokens": None,
        }
    else:
        prov.generate.return_value = {
            "ok": True, "text": "A bar chart of quarterly revenue by region.",
            "reason": providers.REASON_OK,
            "provider": "runpod_serverless", "zone": "cloud", "cost_usd": 0.001,
            "model": "qwen2.5-vl", "latency_ms": 100,
            "prompt_tokens": 10, "completion_tokens": 5,
        }
    return prov


def _local_prov(*, succeed: bool):
    """Fake local Ollama provider."""
    prov = MagicMock()
    prov.name = "ollama"
    if succeed:
        prov.generate.return_value = {
            "ok": True, "text": "A bar chart showing quarterly revenue across regions.",
            "reason": providers.REASON_OK,
            "provider": "ollama", "zone": "local", "cost_usd": 0.0,
            "model": "moondream", "latency_ms": 2000,
            "prompt_tokens": None, "completion_tokens": None,
        }
    else:
        prov.generate.return_value = {
            "ok": False, "text": None, "reason": providers.REASON_TRANSPORT,
            "provider": "ollama", "zone": "local", "cost_usd": 0.0,
            "model": "moondream", "latency_ms": 0,
            "prompt_tokens": None, "completion_tokens": None,
        }
    return prov


# ── W2 warning ─────────────────────────────────────────────────────────────────

def test_w2_warning_logged_on_cloud_fallback(monkeypatch, caplog):
    """A W2: vision-fallback warning must appear in logging when cloud fails and local runs."""
    monkeypatch.setattr(providers, "active_vision_provider", lambda: _cloud_prov(fail=True))
    monkeypatch.setattr(providers, "local_vision_provider", lambda: _local_prov(succeed=True))

    with caplog.at_level(logging.WARNING):
        ai._vision_generate("describe this image", b"FAKE_BYTES")

    hits = [r for r in caplog.records if "W2:" in r.message and "vision-fallback" in r.message]
    assert hits, "Expected a W2: vision-fallback warning in the log"


def test_w2_warning_names_the_cloud_provider(monkeypatch, caplog):
    """The warning must name which cloud provider failed so the operator knows what to check."""
    monkeypatch.setattr(providers, "active_vision_provider", lambda: _cloud_prov(fail=True))
    monkeypatch.setattr(providers, "local_vision_provider", lambda: _local_prov(succeed=True))

    with caplog.at_level(logging.WARNING):
        ai._vision_generate("describe this image", b"FAKE_BYTES")

    hits = [r for r in caplog.records if "W2:" in r.message]
    assert hits and "runpod_serverless" in hits[0].message


def test_no_w2_warning_when_cloud_succeeds(monkeypatch, caplog):
    """No fallback → no W2: warning."""
    monkeypatch.setattr(providers, "active_vision_provider", lambda: _cloud_prov(fail=False))

    with caplog.at_level(logging.WARNING):
        ai._vision_generate("describe this image", b"FAKE_BYTES")

    hits = [r for r in caplog.records if "W2:" in r.message]
    assert not hits, "Unexpected W2: warning when cloud succeeded"


def test_no_w2_warning_for_pure_local_path(monkeypatch, caplog):
    """When the active provider is already Ollama, no fallback occurs and no warning is emitted."""
    monkeypatch.setattr(providers, "active_vision_provider", lambda: _local_prov(succeed=True))

    with caplog.at_level(logging.WARNING):
        ai._vision_generate("describe this image", b"FAKE_BYTES")

    hits = [r for r in caplog.records if "W2:" in r.message]
    assert not hits


# ── vision_fallback flag ───────────────────────────────────────────────────────

def test_describe_image_vision_fallback_true_on_cloud_miss(monkeypatch):
    """describe_image must return vision_fallback=True when cloud fails and local serves."""
    monkeypatch.setattr(providers, "active_vision_provider", lambda: _cloud_prov(fail=True))
    monkeypatch.setattr(providers, "local_vision_provider", lambda: _local_prov(succeed=True))
    monkeypatch.setattr(providers, "cloud_vision_provider", lambda: None)  # no escalation

    result = ai.describe_image(b"FAKE_BYTES", filename="chart.png")

    assert result is not None, "Expected a usable draft after local fallback"
    assert result.get("vision_fallback") is True, "vision_fallback flag must be set on cloud miss"


def test_describe_image_no_vision_fallback_when_cloud_serves(monkeypatch):
    """No vision_fallback key when cloud answers successfully — the happy path."""
    monkeypatch.setattr(providers, "active_vision_provider", lambda: _cloud_prov(fail=False))
    monkeypatch.setattr(providers, "cloud_vision_provider", lambda: None)

    result = ai.describe_image(b"FAKE_BYTES", filename="chart.png")

    assert result is None or not result.get("vision_fallback"), \
        "vision_fallback must not appear when cloud succeeded"


def test_describe_image_no_vision_fallback_for_pure_local(monkeypatch):
    """Pure local Ollama path — no fallback happened, so no flag."""
    monkeypatch.setattr(providers, "active_vision_provider", lambda: _local_prov(succeed=True))
    monkeypatch.setattr(providers, "cloud_vision_provider", lambda: None)

    result = ai.describe_image(b"FAKE_BYTES", filename="chart.png")

    assert result is None or not result.get("vision_fallback"), \
        "vision_fallback must not appear on the pure-local path"


def test_vision_fallback_flag_resets_between_calls(monkeypatch):
    """A fallback in call N must not leak into call N+1 if that one succeeds."""
    call_count = [0]

    def _active():
        call_count[0] += 1
        return _cloud_prov(fail=(call_count[0] == 1))  # first call fails, second succeeds

    monkeypatch.setattr(providers, "active_vision_provider", _active)
    monkeypatch.setattr(providers, "local_vision_provider", lambda: _local_prov(succeed=True))
    monkeypatch.setattr(providers, "cloud_vision_provider", lambda: None)

    result1 = ai.describe_image(b"FAKE_BYTES", filename="chart1.png")
    result2 = ai.describe_image(b"FAKE_BYTES", filename="chart2.png")

    assert result1 is not None and result1.get("vision_fallback") is True
    assert result2 is None or not result2.get("vision_fallback"), \
        "fallback flag from first call must not leak into second call"
