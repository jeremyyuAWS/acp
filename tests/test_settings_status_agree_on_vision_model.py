"""GET /settings and GET /ai/status must never disagree about the configured vision model.

The 2026-07-30 incident: /settings reported `ai_vision_model: moondream` while /ai/status
reported `vision_model: qwen2.5vl:7b` and `vision_available: false`, so WCAG 1.1.1 stopped
routing to a vision model and alt-text drafts degraded to filename-guessed templates. Two
endpoints, one setting, one process, contradicting each other — and with them contradicting
each other there is no way to tell from the outside whether a fix has landed.

They disagree because they answer from different places by construction: /settings reads the
store row, /ai/status reports ai.py's module globals (TTL-refreshed from that same row, so a
GPU burst can be attached and detached without a revision swap). That indirection is
deliberate and worth keeping, but it means "the store says X" and "the platform is using X"
are two separate facts, and only the second one decides what the customer sees.

So pin the bridge between them rather than either side alone:

    non-empty stored override  →  /ai/status.vision_model == that override
    empty / absent            →  /ai/status.vision_model == the deploy default

with config_source labelling which of the two it was. A refresh that stops running, a
comparison that stops firing, or a source label computed from a different place than the
value all break at least one assertion here.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

import ai  # noqa: E402
import core  # noqa: E402

# What acp-ollama actually had during the incident: the text model and the small CPU vision
# model, and never the GPU-only name the stale override still pointed at.
PULLED = [{"name": "llama3.1:8b"}, {"name": "moondream:latest"}]
STALE_GPU_MODEL = "qwen2.5vl:7b"     # from a burst pod that had since been torn down


@pytest.fixture()
def client(monkeypatch, isolated_store):
    """An ungated TestClient with a reachable Ollama that has PULLED and nothing else.

    _fetch_tags is the single network seam; stubbing it keeps vision_available meaningful
    (it is what actually gates real alt text) without a live endpoint.
    """
    from fastapi.testclient import TestClient

    from app import app

    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setattr(core, "ACCESS_CODE", "", raising=False)
    monkeypatch.setattr(core, "GOOGLE_CLIENT_ID", "", raising=False)
    monkeypatch.setattr(core, "E2E_KEY", None, raising=False)
    monkeypatch.setattr(core, "OWNER_EMAIL", "", raising=False)   # PUT /settings is owner-gated
    monkeypatch.setattr(ai, "_fetch_tags", lambda: list(PULLED))

    # The deploy default for this test run, independent of the developer's own env.
    monkeypatch.setitem(ai._ENV_DEFAULTS, "vision", "moondream")
    monkeypatch.setattr(ai, "OLLAMA_VISION_MODEL", ai._ENV_DEFAULTS["vision"], raising=False)
    ai.reset_probe_cache()
    ai._override_checked["at"] = 0.0
    try:
        yield TestClient(app)
    finally:
        # Never leak an override or a probe cache into another test module.
        isolated_store.set_setting("ai_vision_model", "")
        ai._override_checked["at"] = 0.0
        ai._maybe_refresh_endpoint()
        ai.reset_probe_cache()


def _both(client) -> tuple[str, dict]:
    """The configured vision model as each endpoint reports it, plus the whole status body."""
    stored = client.get("/settings").json()["ai_vision_model"]
    status = client.get("/ai/status").json()
    return stored, status


def assert_agree(client) -> dict:
    """The invariant, in one place: whatever /settings says is configured is what /ai/status
    says is in use, and config_source says which of override/env that was."""
    stored, status = _both(client)
    expected = stored or ai._ENV_DEFAULTS["vision"]
    assert status["vision_model"] == expected, (
        f"/settings reports ai_vision_model={stored!r} (effective: {expected!r}) but /ai/status "
        f"reports vision_model={status['vision_model']!r}. The store row and the module globals "
        f"have drifted; every alt-text draft follows the globals, not the row."
    )
    assert status["config_source"]["vision_model"] == ("override" if stored else "env"), (
        f"config_source says {status['config_source']['vision_model']!r} for a stored value of "
        f"{stored!r} — the source label and the value are being computed from different places."
    )
    return status


def test_a_stale_override_is_reported_by_both_endpoints(client, isolated_store):
    """The broken state must at least be legible: both endpoints name the stale model."""
    isolated_store.set_setting("ai_vision_model", STALE_GPU_MODEL)
    status = assert_agree(client)

    assert status["vision_model"] == STALE_GPU_MODEL
    assert status["vision_available"] is False        # qwen was never pulled → no real alt text
    # And the reason must point at the override, not at the endpoint: the fix is one cleared
    # field, and "is Ollama down?" sends the operator to the wrong place for an afternoon.
    reason = status["vision_unavailable_reason"]
    assert "override" in reason and "moondream" in reason


def test_a_put_agrees_on_both_endpoints_immediately(client, isolated_store):
    """No TTL wait. The PUT's own replica must switch within the request, or an operator
    checking /ai/status right after a successful 200 concludes the fix did not apply."""
    isolated_store.set_setting("ai_vision_model", STALE_GPU_MODEL)
    assert_agree(client)

    res = client.put("/settings", json={"ai_vision_model": "moondream"})
    assert res.status_code == 200
    assert res.json()["ai_vision_model"] == "moondream"

    status = assert_agree(client)
    assert status["vision_model"] == "moondream"
    assert status["vision_available"] is True         # the headline feature is back on


def test_clearing_the_override_falls_back_to_the_deploy_default(client, isolated_store):
    """The documented remedy: clear the field, fall back to the env var. Both endpoints must
    agree that the deploy default is now what is in use, and say so is where it came from."""
    isolated_store.set_setting("ai_vision_model", STALE_GPU_MODEL)
    assert_agree(client)

    res = client.put("/settings", json={"ai_vision_model": ""})
    assert res.status_code == 200
    assert res.json()["ai_vision_model"] == ""

    status = assert_agree(client)
    assert status["vision_model"] == "moondream"      # ← the env default, not the cleared override
    assert status["config_source"]["vision_model"] == "env"
    assert status["vision_available"] is True


def test_a_replica_that_missed_the_put_converges_on_its_own(client, isolated_store):
    """acp-app runs up to 3 replicas behind one ingress, so /settings and /ai/status can land
    on different processes. Only the PUT's own replica is switched synchronously; the others
    must catch up from the shared store on the TTL. Simulated here by rewinding this process's
    globals to the pre-PUT value, which is exactly the state such a replica is in.

    Without this, the disagreement is permanent for every replica but one, and which answer an
    operator gets depends on which process the load balancer picked.
    """
    isolated_store.set_setting("ai_vision_model", "moondream")
    ai.OLLAMA_VISION_MODEL = STALE_GPU_MODEL          # a replica still on the old value
    ai._override_checked["at"] = 0.0                  # its TTL has lapsed

    status = assert_agree(client)
    assert status["vision_model"] == "moondream"


def test_the_two_endpoints_read_one_setting_under_one_key(client, isolated_store):
    """A rename on one side is the cheapest way to reintroduce this bug — the writer would
    keep returning 200 and the reader would keep reporting the deploy default forever."""
    isolated_store.set_setting("ai_vision_model", "llava:13b")
    assert client.get("/settings").json()["ai_vision_model"] == "llava:13b"

    ai._override_checked["at"] = 0.0
    ai._maybe_refresh_endpoint()
    assert ai.OLLAMA_VISION_MODEL == "llava:13b"

    src = Path(__file__).resolve().parent.parent / "api"
    assert 'get_setting("ai_vision_model")' in (src / "ai.py").read_text()
    assert '"ai_vision_model"' in (src / "routes" / "system.py").read_text()
