"""AI endpoint config precedence, and what /ai/status is allowed to imply.

Two traps, both of which cost real time on 2026-07-29 when vision alt text was down for a
customer demo:

1. A STORED override outranks the env var, indefinitely and invisibly. `ai_vision_model` still
   held `qwen2.5vl:7b` from a burst GPU pod that had since been torn down. Setting
   OLLAMA_VISION_MODEL on the container app therefore changed nothing, and /ai/status reported
   only the effective value — which reads as "the env var did not apply", not "a saved override
   is winning". /ai/status now names the source.

2. `available: true` meant only that Ollama answered /api/tags. The configured TEXT model
   (`qwen2.5vl:7b`) was not on the container at all, so every generate returned
   404 'model not found' while the status endpoint looked green. Reachability is not capability,
   so model_available is now reported separately.

Also pins that PUT /settings really does persist ai_vision_model — the leading theory during
that investigation was that the field never reached the server, and it was wrong.
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


def _client(monkeypatch, isolated_store):
    monkeypatch.setattr(core, "store", isolated_store)
    from fastapi.testclient import TestClient
    from app import app
    return TestClient(app)


# ── 1. the precedence trap ─────────────────────────────────────────────────────

def test_a_stored_vision_model_outranks_the_env_var(isolated_store, monkeypatch):
    """The exact production state: env says moondream, the store still says qwen — store wins."""
    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setitem(ai._ENV_DEFAULTS, "vision", "moondream")
    monkeypatch.setattr(ai, "reset_probe_cache", lambda: None)
    isolated_store.set_setting("ai_vision_model", "qwen2.5vl:7b")
    try:
        _force_refresh()
        assert ai.OLLAMA_VISION_MODEL == "qwen2.5vl:7b", (
            "a stale stored override must not be silently ignored — but it must be VISIBLE, "
            "which is what config_sources() is for")
        assert ai.config_sources()["vision_model"] == "override"
        # clearing it hands control back to the deploy's env var
        isolated_store.set_setting("ai_vision_model", "")
        _force_refresh()
        assert ai.OLLAMA_VISION_MODEL == "moondream"
        assert ai.config_sources()["vision_model"] == "env"
    finally:
        isolated_store.set_setting("ai_vision_model", "")
        _force_refresh()


def test_config_sources_reports_each_value_independently(isolated_store, monkeypatch):
    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setattr(ai, "reset_probe_cache", lambda: None)
    isolated_store.set_setting("ai_base_url", "https://gpu.example.net")
    isolated_store.set_setting("ai_vision_model", "")
    isolated_store.set_setting("ai_text_model", "")
    try:
        _force_refresh()
        src = ai.config_sources()
        assert src == {"base_url": "override", "vision_model": "env", "model": "env"}
    finally:
        for k in ("ai_base_url", "ai_vision_model", "ai_text_model"):
            isolated_store.set_setting(k, "")
        _force_refresh()


def test_config_sources_survives_a_store_outage(monkeypatch):
    """Never let a status endpoint 500 because the DB blinked."""
    class _Boom:
        def get_setting(self, *a, **k):
            raise RuntimeError("db down")
    monkeypatch.setattr(core, "store", _Boom())
    assert ai.config_sources() == {"base_url": "env", "vision_model": "env", "model": "env"}


# ── 2. reachable is not capable ────────────────────────────────────────────────

def test_reachable_ollama_without_the_configured_text_model_is_not_available_for_text(monkeypatch):
    """is_available() stays true (Ollama answered) while model_available is false."""
    monkeypatch.setattr(ai, "_maybe_refresh_endpoint", lambda: None)
    monkeypatch.setattr(ai, "_tags_cached", lambda: [{"name": "moondream:latest"},
                                                     {"name": "llama3.1:8b"}])
    monkeypatch.setattr(ai, "OLLAMA_MODEL", "qwen2.5vl:7b")
    monkeypatch.setattr(ai, "OLLAMA_VISION_MODEL", "qwen2.5vl:7b")
    assert ai.is_available() is True          # the reading that misled everyone
    assert ai.model_is_available() is False   # ...and the one that was actually true
    assert ai.vision_is_available() is False


def test_a_bare_model_name_matches_the_latest_tag(monkeypatch):
    """`moondream` must match `moondream:latest`, the way Ollama resolves it itself."""
    monkeypatch.setattr(ai, "_maybe_refresh_endpoint", lambda: None)
    monkeypatch.setattr(ai, "_tags_cached", lambda: [{"name": "moondream:latest"},
                                                     {"name": "llama3.1:8b"}])
    monkeypatch.setattr(ai, "OLLAMA_MODEL", "llama3.1:8b")
    monkeypatch.setattr(ai, "OLLAMA_VISION_MODEL", "moondream")
    assert ai.model_is_available() is True
    assert ai.vision_is_available() is True


def test_an_unreachable_ollama_is_capable_of_nothing(monkeypatch):
    monkeypatch.setattr(ai, "_maybe_refresh_endpoint", lambda: None)
    monkeypatch.setattr(ai, "_tags_cached", lambda: None)
    assert ai.model_is_available() is False
    assert ai.vision_is_available() is False


# ── 3. /ai/status tells the operator both things ───────────────────────────────

def test_ai_status_reports_model_presence_and_config_source(monkeypatch, isolated_store):
    c = _client(monkeypatch, isolated_store)
    monkeypatch.setattr(ai, "_maybe_refresh_endpoint", lambda: None)
    monkeypatch.setattr(ai, "_tags_cached", lambda: [{"name": "moondream:latest"},
                                                     {"name": "llama3.1:8b"}])
    monkeypatch.setattr(ai, "OLLAMA_MODEL", "qwen2.5vl:7b")
    monkeypatch.setattr(ai, "OLLAMA_VISION_MODEL", "qwen2.5vl:7b")
    isolated_store.set_setting("ai_vision_model", "qwen2.5vl:7b")
    try:
        body = c.get("/ai/status").json()
        assert body["available"] is True
        assert body["vision_available"] is False
        assert body["model_available"] is False, \
            "a green 'available' beside a missing model is what hid this for a day"
        assert body["config_source"]["vision_model"] == "override"
    finally:
        isolated_store.set_setting("ai_vision_model", "")


# ── 4. the settings PUT really does carry the vision model ─────────────────────

def test_put_settings_persists_the_vision_model(monkeypatch, isolated_store):
    monkeypatch.setattr(core, "OWNER_EMAIL", "")        # local-dev no-auth path
    c = _client(monkeypatch, isolated_store)
    r = c.put("/settings", json={"ai_base_url": "", "ai_vision_model": "moondream"})
    assert r.status_code == 200, r.text
    assert isolated_store.get_setting("ai_vision_model") == "moondream"
    assert r.json()["ai_vision_model"] == "moondream"   # the response echoes what was stored
    isolated_store.set_setting("ai_vision_model", "")


def test_put_settings_leaves_omitted_keys_alone(monkeypatch, isolated_store):
    """A patch that names only one field must not blank the others."""
    monkeypatch.setattr(core, "OWNER_EMAIL", "")
    c = _client(monkeypatch, isolated_store)
    isolated_store.set_setting("ai_vision_model", "moondream")
    r = c.put("/settings", json={"drive_mirror_folder": "Fixed"})
    assert r.status_code == 200, r.text
    assert isolated_store.get_setting("ai_vision_model") == "moondream"
    isolated_store.set_setting("ai_vision_model", "")


def test_put_settings_is_owner_only(monkeypatch, isolated_store):
    """The 403 the SPA now uses to render the form read-only instead of editable."""
    monkeypatch.setattr(core, "OWNER_EMAIL", "owner@example.com")
    c = _client(monkeypatch, isolated_store)
    r = c.put("/settings", json={"ai_vision_model": "moondream"})
    assert r.status_code == 403
    assert isolated_store.get_setting("ai_vision_model") in (None, "")
