"""'Draft with AI' must be able to look at the image.

/ai/suggest never passed image bytes, and ai.suggest_fix only consults the vision model when
handed them — so WCAG 1.1.1 always fell through to the text model, which is explicitly told it
cannot see and to emit a fill-in template. The reviewer got a guess derived from the filename,
under a message claiming a vision model had described the image.
"""
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

import ai as _ai  # noqa: E402


# ── ai.suggest_fix: the image is what unlocks vision ──────────────────────────

def test_image_bytes_reach_the_vision_model(monkeypatch):
    seen = {}

    def fake_describe(img, *, filename="", context="", style="", **_):
        seen["img"] = img
        return {"alt": "A nurse reviews a chart with a patient.", "model": "llava:7b"}

    monkeypatch.setattr(_ai, "describe_image", fake_describe)
    out = _ai.suggest_fix("1.1.1", "Non-text Content", "A", "deck.pptx", image_bytes=b"PNGBYTES")
    assert seen["img"] == b"PNGBYTES"
    assert out["is_template"] is False
    assert out["suggestion"] == "A nurse reviews a chart with a patient."
    assert out["model"] == "llava:7b"
    assert "reason" not in out          # a real description explains itself


def test_without_an_image_1_1_1_can_only_template(monkeypatch):
    """The regression. No bytes → vision is never consulted → a filename guess."""
    called = []
    monkeypatch.setattr(_ai, "describe_image", lambda *a, **k: called.append(1))

    import httpx

    class _R:
        @staticmethod
        def raise_for_status(): pass
        @staticmethod
        def json(): return {"response": "Describe: [what the image shows]"}

    monkeypatch.setattr(httpx, "post", lambda *a, **k: _R())
    out = _ai.suggest_fix("1.1.1", "Non-text Content", "A", "deck.pptx")
    assert called == []                                  # vision never asked
    assert out["is_template"] is True
    assert "cannot see the image" in out["reason"]       # honest about WHY


def test_vision_that_fails_falls_back_and_says_so(monkeypatch):
    """Bytes in hand but no vision model → template, with a DIFFERENT reason."""
    monkeypatch.setattr(_ai, "describe_image", lambda *a, **k: None)

    import httpx

    class _R:
        @staticmethod
        def raise_for_status(): pass
        @staticmethod
        def json(): return {"response": "Describe: [what the image shows]"}

    monkeypatch.setattr(httpx, "post", lambda *a, **k: _R())
    out = _ai.suggest_fix("1.1.1", "Non-text Content", "A", "d.pptx", image_bytes=b"X")
    assert out["is_template"] is True
    assert "no vision model is available" in out["reason"]


# ── Gap 1 (#367 follow-up): the escalation path reaches the draft response ─────
# describe_image now escalates like describe_image_structured, and suggest_fix + /ai/suggest
# forward the honest processing provenance so the review card reads a REAL field instead of
# re-deriving the escalation path from the ai_calls ledger. Additive + vision-only + no secret.

class _Cloud:
    """A stubbed enabled+key-present cloud vision provider (no real key, no network)."""
    name = "azure_openai"
    zone = "tenant"

    def generate(self, prompt, image_bytes, *, model=None, timeout=120.0):
        return {"text": "Bar chart of quarterly revenue by region", "model": "gpt-4o",
                "provider": "azure_openai", "zone": "tenant", "ok": True,
                "cost_usd": 0.0032, "latency_ms": 800}


def test_describe_image_escalates_when_local_is_unusable(monkeypatch):
    """No cloud → None (unchanged). Cloud enabled + local unusable → escalate, and the numbered
    path + provider + zone come back on the result."""
    monkeypatch.setattr(_ai, "_vision_generate", lambda *a, **k: "")   # local returns nothing usable
    monkeypatch.setattr("providers.cloud_vision_provider", lambda: _Cloud())
    out = _ai.describe_image(b"IMGBYTES", filename="chart.png")
    assert out["alt"] == "Bar chart of quarterly revenue by region"
    assert out["model"] == "gpt-4o" and out["provider"] == "azure_openai"
    assert out["processing_zone"] == "tenant" and out["cost_usd"] == 0.0032
    steps = out["escalation"]
    assert steps[0]["provider"] == "ollama" and steps[1]["provider"] == "azure_openai"


def test_describe_image_local_draft_reports_zone_but_never_escalates(monkeypatch):
    """A usable local draft stays local: provider/processing_zone are reported honestly, and no
    cloud provider is ever consulted, so no escalation key appears."""
    monkeypatch.setattr(_ai, "_vision_generate",
                        lambda *a, **k: "A nurse reviews a chart with a patient.")
    called = {"cloud": 0}
    monkeypatch.setattr("providers.cloud_vision_provider",
                        lambda: called.__setitem__("cloud", called["cloud"] + 1))
    out = _ai.describe_image(b"IMGBYTES", filename="p.png")
    assert called["cloud"] == 0                          # grounded/usable → cloud never consulted
    assert out["provider"] == "ollama" and out["processing_zone"] == "local"
    assert "escalation" not in out and "cost_usd" not in out


def test_suggest_fix_forwards_escalation_fields_only_for_vision(monkeypatch):
    monkeypatch.setattr(_ai, "describe_image", lambda *a, **k: {
        "alt": "Bar chart of quarterly revenue by region", "model": "gpt-4o",
        "provider": "azure_openai", "processing_zone": "customer_cloud",
        "escalation": [{"provider": "ollama"}, {"provider": "azure_openai"}], "cost_usd": 0.0032})
    out = _ai.suggest_fix("1.1.1", "Non-text Content", "A", "chart.pptx", image_bytes=b"X")
    assert out["is_template"] is False
    assert out["provider"] == "azure_openai" and out["processing_zone"] == "customer_cloud"
    assert out["escalation"][1]["provider"] == "azure_openai" and out["cost_usd"] == 0.0032

    # A non-vision criterion (text template) carries none of these keys.
    import httpx

    class _R:
        @staticmethod
        def raise_for_status(): pass
        @staticmethod
        def json(): return {"response": "Rename the file descriptively."}
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _R())
    txt = _ai.suggest_fix("2.4.4", "Link Purpose", "A", "d.docx")
    for k in ("provider", "processing_zone", "escalation", "cost_usd"):
        assert k not in txt


def _stub_core_status(monkeypatch, trace):
    import core
    monkeypatch.setattr(core, "store", types.SimpleNamespace(
        get_ai_enabled=lambda: True,
        get_trace_row=lambda s, f, r: trace))


def test_ai_suggest_route_returns_escalation_and_leaks_no_secret(monkeypatch):
    """End to end through the route: a cloud-escalated 1.1.1 draft carries the numbered path,
    provider, and zone in the /ai/suggest payload — and nothing that resembles a secret."""
    import routes.ai as rai
    _stub_core_status(monkeypatch, {"rule_name": "Non-text Content", "level": "A", "detail": ""})
    monkeypatch.setattr(_ai, "model_is_available", lambda: False)
    monkeypatch.setattr(_ai, "vision_is_available", lambda: True)
    monkeypatch.setattr(rai, "_image_for_locator", lambda *a, **k: b"THE-IMAGE")
    # real suggest_fix runs; only the local vision + cloud provider seams are stubbed
    monkeypatch.setattr(_ai, "_vision_generate", lambda *a, **k: "")
    monkeypatch.setattr("providers.cloud_vision_provider", lambda: _Cloud())

    req = types.SimpleNamespace(state=types.SimpleNamespace(user_email=None))
    out = rai.ai_suggest(request=req, scan_id="s1", file="chart.pptx", rule_id="1.1.1",
                         locator="ppt/slides/slide1.xml#rId2")
    assert out["provider"] == "azure_openai" and out["processing_zone"] == "tenant"
    assert out["escalation"][1]["provider"] == "azure_openai"
    blob = repr(out).lower()
    assert "key_secret_ref" not in blob and "api-key" not in blob and "sk-" not in blob


# ── the route wires the locator through ───────────────────────────────────────

def _stub_core(monkeypatch, trace):
    import core
    monkeypatch.setattr(core, "store", types.SimpleNamespace(
        get_ai_enabled=lambda: True,
        get_trace_row=lambda s, f, r: trace))


def test_route_hands_the_located_image_to_suggest_fix(monkeypatch):
    import routes.ai as rai
    _stub_core(monkeypatch, {"rule_name": "Non-text Content", "level": "A", "detail": ""})
    # 1.1.1 with an image is the one criterion the VISION model can serve on its own, so that
    # is the gate the route consults for it — a text-only miss must not close this path.
    monkeypatch.setattr(_ai, "model_is_available", lambda: False)
    monkeypatch.setattr(_ai, "vision_is_available", lambda: True)
    monkeypatch.setattr(rai, "_image_for_locator", lambda *a, **k: b"THE-IMAGE")

    got = {}

    def fake_suggest(**kw):
        got.update(kw)
        return {"suggestion": "alt", "is_template": False}

    monkeypatch.setattr(_ai, "suggest_fix", fake_suggest)
    rai.ai_suggest(request=object(), scan_id="s1", file="deck.pptx", rule_id="1.1.1",
                   locator="ppt/slides/slide1.xml#rId2")
    assert got["image_bytes"] == b"THE-IMAGE"


def test_route_never_fetches_an_image_for_a_non_image_criterion(monkeypatch):
    """2.4.4 link purpose has no picture; don't re-download the document to find one."""
    import routes.ai as rai
    _stub_core(monkeypatch, {"rule_name": "Link Purpose", "level": "A", "detail": ""})
    monkeypatch.setattr(_ai, "model_is_available", lambda: True)
    monkeypatch.setattr(rai, "_image_for_locator",
                        lambda *a, **k: pytest.fail("must not fetch an image for 2.4.4"))

    got = {}
    monkeypatch.setattr(_ai, "suggest_fix", lambda **kw: (got.update(kw), {"suggestion": "x"})[1])
    rai.ai_suggest(request=object(), scan_id="s1", file="p.docx", rule_id="2.4.4", locator=None)
    assert got["image_bytes"] is None


def test_image_lookup_degrades_to_none_when_source_is_unreachable(monkeypatch):
    """Every failure in the fetch ladder must return None, never 500 the review inbox."""
    import routes.ai as rai
    import routes.scans as rs
    monkeypatch.setattr(rs, "_source_bytes_for_render", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("drive down")))
    assert rai._image_for_locator(object(), "s1", "d.pptx", "word/document.xml#rId9") is None


def test_image_lookup_is_skipped_without_a_locator():
    import routes.ai as rai
    assert rai._image_for_locator(object(), "s1", "d.pptx", None) is None
