"""Preflight covers the CURRENT GPU vision path — ollama pointing at an Azure GPU host.

The prior check_gpu was RunPod-only (ADR 0022 era). Since #405 the GPU runs as ACP_VISION_PROVIDER=
ollama with OLLAMA_BASE_URL at the GPU, so the old check would (a) flag today's correct config as
"the GPU provider is NOT what a scan will use", and (b) never probe reachability + the vision MODEL
being present — the exact silent failure #302 was (a reachable endpoint whose baked model was
shadowed by the container VOLUME, so vision produced nothing for 45 days, no error). These pin the
fix: ollama@GPU is a valid provider, the local-floor-while-RunPod-configured trap still FAILs, and
--live reuses the runtime's own vision_unavailable_reason() so a shadowed/absent model FAILs loudly.
"""
import importlib
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "api"))

_GPU_VARS = ("RUNPOD_ENDPOINT_ID", "RUNPOD_API_KEY", "ACP_VISION_PROVIDER")


class _FakeProvider:
    def __init__(self, name, zone, base_url=""):
        self.name, self.zone, self.base_url = name, zone, base_url


def _run(monkeypatch, *, env, provider, live=False, vision_reason=...):
    for k in _GPU_VARS:
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    import preflight
    importlib.reload(preflight)

    prov_mod = types.ModuleType("providers")
    prov_mod.active_vision_provider = lambda: provider
    monkeypatch.setitem(sys.modules, "providers", prov_mod)
    if vision_reason is not ...:                       # only stub ai when a --live probe will run
        ai_mod = types.ModuleType("ai")
        ai_mod.vision_unavailable_reason = lambda: vision_reason
        ai_mod.OLLAMA_VISION_MODEL = "llava:13b"
        ai_mod.OLLAMA_BASE_URL = provider.base_url or "http://x"
        monkeypatch.setitem(sys.modules, "ai", ai_mod)

    preflight.results.clear()
    preflight.check_gpu(live)
    return {r["check"]: (r["state"], r["detail"]) for r in preflight.results}


def test_ollama_at_a_gpu_endpoint_is_a_valid_provider_not_a_misconfig(monkeypatch):
    # ollama pointing at a remote GPU host (zone=cloud), no RunPod configured — the current path, PASS.
    r = _run(monkeypatch, env={"ACP_VISION_PROVIDER": "ollama"},
             provider=_FakeProvider("ollama", "cloud", "https://acp-ollama-gpu.westus2.example"))
    assert r["resolved provider"][0] == "PASS"
    assert "GPU/remote endpoint" in r["resolved provider"][1]


def test_ollama_cpu_floor_while_runpod_configured_is_the_trap_fail(monkeypatch):
    # RunPod configured (the GPU was *meant* to be RunPod) yet resolved to the LOCAL cpu floor —
    # the ADR 0022 trap this check exists for.
    r = _run(monkeypatch, env={"RUNPOD_ENDPOINT_ID": "e", "RUNPOD_API_KEY": "k"},
             provider=_FakeProvider("ollama", "local", "http://acp-ollama.internal"))
    assert r["resolved provider"][0] == "FAIL"
    assert "RunPod is configured but NOT selected" in r["resolved provider"][1]


def test_live_probe_passes_when_the_vision_model_is_present(monkeypatch):
    r = _run(monkeypatch, env={"ACP_VISION_PROVIDER": "ollama"},
             provider=_FakeProvider("ollama", "cloud", "https://gpu"),
             live=True, vision_reason=None)
    assert r["endpoint reachable"][0] == "PASS"
    assert "llava:13b" in r["endpoint reachable"][1]


def test_live_probe_fails_loudly_when_the_model_is_shadowed_or_absent(monkeypatch):
    # The #302 case: reachable, but the vision model is not present. The runtime's reason is surfaced
    # verbatim as a FAIL — a bare reachability probe would have passed in exactly this state.
    reason = ("the configured vision model 'llava:13b' is not present at https://gpu "
              "(available: llama3.1:8b)")
    r = _run(monkeypatch, env={"ACP_VISION_PROVIDER": "ollama"},
             provider=_FakeProvider("ollama", "cloud", "https://gpu"),
             live=True, vision_reason=reason)
    assert r["endpoint reachable"][0] == "FAIL"
    assert r["endpoint reachable"][1] == reason


def test_not_live_says_it_did_not_probe_rather_than_borrowing_pass(monkeypatch):
    r = _run(monkeypatch, env={"ACP_VISION_PROVIDER": "ollama"},
             provider=_FakeProvider("ollama", "cloud", "https://gpu"))
    assert r["endpoint reachable"][0] == "WARN"          # "we did not look" ≠ "we looked, fine"
