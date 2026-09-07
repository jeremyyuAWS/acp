"""Optional vision failures must not monopolize the assessment worker pool."""
from types import SimpleNamespace

import ai
import providers


class _Provider:
    name = "ollama"
    zone = "cloud"
    base_url = "https://gpu.example"
    model = "llava:13b"

    def __init__(self, results):
        self.results = list(results)
        self.calls = 0

    def generate(self, *args, **kwargs):
        self.calls += 1
        return self.results.pop(0)


def _result(*, ok=False, reason=providers.REASON_TRANSPORT, text=None):
    return {"ok": ok, "reason": reason, "text": text, "model": "llava:13b",
            "provider": "ollama", "zone": "cloud", "cost_usd": 0.0}


def _wire(monkeypatch, provider, tags):
    ai.reset_vision_circuits()
    monkeypatch.setattr(providers, "active_vision_provider", lambda: provider)
    monkeypatch.setattr(ai, "_tags_cached", lambda: tags)
    monkeypatch.setattr(ai, "_trace_ai", lambda *args, **kwargs: None)


def test_missing_alternate_model_is_skipped_before_generate(monkeypatch, capsys):
    provider = _Provider([_result(ok=True, text="should not run")])
    _wire(monkeypatch, provider, [{"name": "llava:13b"}])

    assert ai._vision_generate("validate", b"IMG", model="minicpm-v:latest") is None
    assert provider.calls == 0
    assert "model is not installed" in capsys.readouterr().out


def test_transport_failure_opens_then_recovers_circuit(monkeypatch):
    provider = _Provider([
        _result(reason=providers.REASON_TRANSPORT),
        _result(ok=True, reason=providers.REASON_OK, text="A useful chart description"),
    ])
    _wire(monkeypatch, provider, [{"name": "llava:13b"}])
    clock = SimpleNamespace(now=100.0)
    monkeypatch.setattr(ai.time, "monotonic", lambda: clock.now)
    monkeypatch.setattr(ai, "VISION_CIRCUIT_FAILURES", 1)
    monkeypatch.setattr(ai, "VISION_CIRCUIT_COOLDOWN", 120.0)

    assert ai._vision_generate("describe", b"IMG", scan_id="scan-1") is None
    assert ai._vision_generate("describe", b"IMG", scan_id="scan-1") is None
    assert provider.calls == 1

    clock.now += 121
    assert ai._vision_generate("describe", b"IMG", scan_id="scan-1") == "A useful chart description"
    assert provider.calls == 2
