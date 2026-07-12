"""Runtime AI-endpoint override (GPU burst without a restart).

The endpoint used to live only in env vars, so pointing at a burst GPU meant a container
revision swap — the root cause of the 2026-07-11 wedged-scan incident. The admin settings
override is TTL-refreshed into ai.py's module globals, so every replica follows within
seconds and running scans are never disturbed. Empty settings = env defaults, unchanged.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))
import ai  # noqa: E402
import core  # noqa: E402


def _force_refresh():
    ai._override_checked["at"] = 0.0
    ai._maybe_refresh_endpoint()


def test_override_switches_the_globals_and_resets_the_probe(isolated_store, monkeypatch):
    monkeypatch.setattr(core, "store", isolated_store)
    probe_resets = []
    monkeypatch.setattr(ai, "reset_probe_cache", lambda: probe_resets.append(1))
    isolated_store.set_setting("ai_base_url", "https://gpu.example.net/")
    isolated_store.set_setting("ai_vision_model", "llava:13b")
    _force_refresh()
    try:
        assert ai.OLLAMA_BASE_URL == "https://gpu.example.net"      # trailing slash stripped
        assert ai.OLLAMA_VISION_MODEL == "llava:13b"
        assert probe_resets, "a switched endpoint must re-probe availability"
        # clearing the settings restores the deploy defaults
        isolated_store.set_setting("ai_base_url", "")
        isolated_store.set_setting("ai_vision_model", "")
        _force_refresh()
        assert ai.OLLAMA_BASE_URL == ai._ENV_DEFAULTS["base"]
        assert ai.OLLAMA_VISION_MODEL == ai._ENV_DEFAULTS["vision"]
    finally:
        # never leak an override into other tests
        isolated_store.set_setting("ai_base_url", "")
        isolated_store.set_setting("ai_vision_model", "")
        _force_refresh()


def test_ttl_prevents_a_store_read_per_call(isolated_store, monkeypatch):
    monkeypatch.setattr(core, "store", isolated_store)
    reads = []
    orig = isolated_store.get_setting
    monkeypatch.setattr(isolated_store, "get_setting",
                        lambda k, d=None: (reads.append(k), orig(k, d))[1])
    _force_refresh()
    n = len(reads)
    ai._maybe_refresh_endpoint()          # inside the TTL window — no new reads
    ai._maybe_refresh_endpoint()
    assert len(reads) == n


def test_store_failure_leaves_the_endpoint_untouched(monkeypatch):
    before = ai.OLLAMA_BASE_URL
    class _Boom:
        def get_setting(self, *a, **k):
            raise RuntimeError("db down")
    monkeypatch.setattr(core, "store", _Boom())
    _force_refresh()
    assert ai.OLLAMA_BASE_URL == before


def test_provenance_zone_follows_the_override(isolated_store, monkeypatch):
    monkeypatch.setattr(core, "store", isolated_store)
    isolated_store.set_setting("ai_base_url", "https://abc-11434.proxy.runpod.net")
    _force_refresh()
    try:
        assert ai.provenance()["zone"] == "cloud"        # bytes leave the network — badge says so
        isolated_store.set_setting("ai_base_url", "")
        _force_refresh()
    finally:
        isolated_store.set_setting("ai_base_url", "")
        _force_refresh()
