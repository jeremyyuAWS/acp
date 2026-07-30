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


# ── An override that outlives what it was for (2026-07-29) ─────────────────────────
# Detaching a burst GPU means clearing TWO fields. Clearing only the base URL left
# 'qwen2.5vl:7b' pinned in the store, and because the store beats the env the platform kept
# asking the CPU box for a model it had never had. vision_available:false was the whole
# symptom, so the diagnosis went to the container and every env-var fix landed underneath
# an override nobody could see.


def _fake_tags(monkeypatch, *names):
    monkeypatch.setattr(ai, "_tags_cached", lambda: [{"name": n} for n in names])


def test_reason_names_the_override_and_the_default_it_is_shadowing(isolated_store, monkeypatch):
    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setitem(ai._ENV_DEFAULTS, "vision", "moondream")
    isolated_store.set_setting("ai_vision_model", "qwen2.5vl:7b")
    _force_refresh()
    try:
        _fake_tags(monkeypatch, "llama3.1:8b", "moondream")
        assert ai.vision_is_available() is False
        why = ai.vision_unavailable_reason()
        assert "qwen2.5vl:7b" in why                  # the name that is actually wrong
        assert "moondream" in why                     # ...and the default it is hiding
        assert "override" in why.lower()              # ...and that a setting, not the box, did it
    finally:
        isolated_store.set_setting("ai_vision_model", "")
        _force_refresh()


def test_a_deploy_default_that_is_missing_is_not_blamed_on_an_override(isolated_store, monkeypatch):
    """The source clause comes from config_sources(), i.e. from the store — not from comparing the
    effective name against _ENV_DEFAULTS. With no override set, a missing model is the deploy's
    own default and telling the admin to 'clear the Vision model field' would be a dead end."""
    monkeypatch.setattr(core, "store", isolated_store)
    isolated_store.set_setting("ai_vision_model", "")
    _force_refresh()
    monkeypatch.setattr(ai, "OLLAMA_VISION_MODEL", "moondream")
    monkeypatch.setattr(ai, "_maybe_refresh_endpoint", lambda: None)
    _fake_tags(monkeypatch, "llama3.1:8b")
    why = ai.vision_unavailable_reason()
    assert "moondream" in why
    assert "override" not in why.lower()


def test_no_reason_when_vision_works(isolated_store, monkeypatch):
    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setattr(ai, "OLLAMA_VISION_MODEL", "moondream")
    _fake_tags(monkeypatch, "moondream")
    monkeypatch.setattr(ai, "_maybe_refresh_endpoint", lambda: None)
    assert ai.vision_unavailable_reason() is None


def test_unreachable_endpoint_is_not_reported_as_a_bad_model_name(monkeypatch):
    monkeypatch.setattr(ai, "_tags_cached", lambda: None)
    monkeypatch.setattr(ai, "_maybe_refresh_endpoint", lambda: None)
    why = ai.vision_unavailable_reason()
    assert "not reachable" in why
    assert "not present" not in why          # a down endpoint says nothing about the model name


def test_a_rejected_base_url_writes_nothing_at_all(isolated_store, monkeypatch):
    """The server side of the "it will not save" report: the SPA sends both fields in one Apply,
    and a scheme-less URL refuses the whole PUT, so the vision-model change the admin made in the
    same Apply does not take effect either.

    This held before the all-or-nothing refactor too — ai_base_url carries the only rule and is
    checked first, so nothing had been written by the time it raised. Pinned because that was an
    accident of ordering, not a guarantee; see
    test_no_field_is_written_when_a_later_field_is_invalid for the property itself."""
    import routes.system as system
    from fastapi import HTTPException
    monkeypatch.setattr(system.core, "store", isolated_store)
    monkeypatch.setattr(system.core, "OWNER_EMAIL", "")        # _require_admin no-ops in local dev
    isolated_store.set_setting("ai_vision_model", "qwen2.5vl:7b")

    class _Req:
        state = type("S", (), {"user_email": None})()

    body = system.SettingsUpdate(ai_base_url="gpu.example.net", ai_vision_model="moondream")
    try:
        system.update_settings(body, _Req())
    except HTTPException as e:
        assert e.status_code == 422
    else:
        raise AssertionError("a scheme-less ai_base_url must still be rejected")
    # all-or-nothing: the rejected request changed NEITHER field
    assert isolated_store.get_setting("ai_vision_model") == "qwen2.5vl:7b"
    assert (isolated_store.get_setting("ai_base_url") or "") == ""


def test_no_field_is_written_when_a_later_field_is_invalid(isolated_store, monkeypatch):
    """The all-or-nothing property, independent of field order.

    Installing a rule on ai_vision_model — a field the write loop reaches AFTER ai_base_url —
    is what tells the two implementations apart: validate-and-write in one pass would have
    stored the valid base URL and only then raised, leaving the endpoint switched to a pod the
    admin never got to finish configuring. Every validator now runs first, so a rejected PUT
    leaves the stored settings exactly as they were."""
    import routes.system as system
    from fastapi import HTTPException
    monkeypatch.setattr(system.core, "store", isolated_store)
    monkeypatch.setattr(system.core, "OWNER_EMAIL", "")
    monkeypatch.setitem(system._AI_VALIDATORS, "ai_vision_model",
                        lambda v: "vision model rejected by this test" if v else None)

    class _Req:
        state = type("S", (), {"user_email": None})()

    body = system.SettingsUpdate(ai_base_url="https://gpu.example.net", ai_vision_model="moondream")
    try:
        system.update_settings(body, _Req())
    except HTTPException as e:
        assert e.status_code == 422
    else:
        raise AssertionError("the installed ai_vision_model validator must reject the PUT")
    # the VALID field, which the loop would have reached first, must not have been written
    assert (isolated_store.get_setting("ai_base_url") or "") == ""
    assert (isolated_store.get_setting("ai_vision_model") or "") == ""


def test_a_valid_apply_writes_both_fields(isolated_store, monkeypatch):
    import routes.system as system
    monkeypatch.setattr(system.core, "store", isolated_store)
    monkeypatch.setattr(system.core, "OWNER_EMAIL", "")

    class _Req:
        state = type("S", (), {"user_email": None})()

    system.update_settings(
        system.SettingsUpdate(ai_base_url="https://gpu.example.net", ai_vision_model="moondream"),
        _Req())
    assert isolated_store.get_setting("ai_base_url") == "https://gpu.example.net"
    assert isolated_store.get_setting("ai_vision_model") == "moondream"
    # and clearing both is how a detach gets back to the deploy default
    system.update_settings(system.SettingsUpdate(ai_base_url="", ai_vision_model=""), _Req())
    assert (isolated_store.get_setting("ai_base_url") or "") == ""
    assert (isolated_store.get_setting("ai_vision_model") or "") == ""
