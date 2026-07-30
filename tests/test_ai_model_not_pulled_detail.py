"""The 503 body for "Ollama is up but the model is not pulled" is a contract the SPA reads.

`frontend/src/api.js` matches `model not pulled` in a 503 detail and flags the error
(`aiModelNotPulled`). `frontend/src/autoDraft.js` then trips a circuit breaker: the remaining
cards in the inbox stop firing a draft request that would fail identically, and show the reason
instead. Before that, a 40-finding inbox discovered the same missing model 40 times and said
nothing until each card's own attempt came back.

So the string is load-bearing in both directions:

  * It MUST appear when the model is genuinely absent, or the breaker never trips and the inbox
    goes back to N doomed requests with no explanation.
  * It MUST NOT appear on the other 503s from the same routes. `explain_finding`/`suggest_fix`
    returning None means the model IS pulled and the call failed — a transient condition that has
    to stay retryable per card. A breaker tripped on that would suppress drafting for the whole
    inbox over one timeout.

Same pattern, and the same reason, as tests/test_scan_not_found_detail.py.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

API = Path(__file__).resolve().parent.parent / "api"
sys.path.insert(0, str(API))
import ai  # noqa: E402
import core  # noqa: E402
import routes.ai as rai  # noqa: E402

MARKER = "model not pulled"


@pytest.fixture
def ollama_only(monkeypatch):
    """Force the Ollama-only backend and a store that says AI is on and the trace is absent.

    The absent trace matters: it 404s immediately AFTER the availability gate, so a test that
    reaches it has proved the gate let the request through.
    """
    monkeypatch.setenv("ACP_AI_BACKEND", "ollama")
    monkeypatch.setattr(core, "store", type("S", (), {
        "get_ai_enabled": staticmethod(lambda: True),
        "get_trace_row": staticmethod(lambda *a: None),
        "get_issue_rule_ids": staticmethod(lambda *a: [])})())


def _detail(fn, **kw):
    with pytest.raises(HTTPException) as e:
        fn(**kw)
    return e.value.status_code, e.value.detail


# ── the marker is present exactly when the model is absent ─────────────────────
def test_the_marker_is_in_the_module_and_the_regex_the_spa_uses_matches_it():
    """Pin the constant itself, so renaming it cannot quietly break the client."""
    assert rai.MODEL_NOT_PULLED == MARKER
    api_js = (Path(__file__).resolve().parent.parent / "frontend" / "src" / "api.js").read_text()
    assert "model not pulled" in api_js, "the SPA's matcher and this marker have drifted apart"


@pytest.mark.parametrize("rule_id", ["2.4.4", "1.1.1", "2.4.10"])
def test_suggest_marks_a_reachable_ollama_with_no_models(ollama_only, monkeypatch, rule_id):
    monkeypatch.setattr(ai, "is_available", lambda: True)
    monkeypatch.setattr(ai, "model_is_available", lambda: False)
    monkeypatch.setattr(ai, "vision_is_available", lambda: False)
    code, detail = _detail(rai.ai_suggest, request=object(), scan_id="s1", file="p.docx",
                           rule_id=rule_id)
    assert code == 503
    assert MARKER in detail
    # The marker is for the machine; the rest has to be actionable for the human reading the card.
    assert ai.OLLAMA_MODEL in detail and "ollama pull" in detail


def test_explain_marks_it_too(ollama_only, monkeypatch):
    monkeypatch.setattr(ai, "is_available", lambda: True)
    monkeypatch.setattr(ai, "model_is_available", lambda: False)
    code, detail = _detail(rai.ai_explain, scan_id="s1", file="p.docx", rule_id="2.4.4")
    assert code == 503 and MARKER in detail


# ── and absent on every other 503 from these routes ───────────────────────────
def test_an_unreachable_ollama_is_not_marked(ollama_only, monkeypatch):
    """"Ollama is down" is a different fix and a retryable one — it must not trip the breaker."""
    monkeypatch.setattr(ai, "is_available", lambda: False)
    monkeypatch.setattr(ai, "model_is_available", lambda: False)
    monkeypatch.setattr(ai, "vision_is_available", lambda: False)
    for fn, kw in ((rai.ai_explain, dict(scan_id="s1", file="p.docx", rule_id="2.4.4")),
                   (rai.ai_suggest, dict(request=object(), scan_id="s1", file="p.docx",
                                         rule_id="2.4.4"))):
        code, detail = _detail(fn, **kw)
        assert code == 503 and MARKER not in detail
        assert "is Ollama running?" in detail


def test_a_failed_call_on_a_pulled_model_is_not_marked(ollama_only, monkeypatch):
    """The model is present and the generate failed. Retryable per card, so: no marker.

    This is the case a breaker must never swallow — one timeout would otherwise stop the whole
    inbox from drafting.
    """
    monkeypatch.setattr(ai, "is_available", lambda: True)
    monkeypatch.setattr(ai, "model_is_available", lambda: True)
    monkeypatch.setattr(ai, "vision_is_available", lambda: True)
    monkeypatch.setattr(core, "store", type("S", (), {
        "get_ai_enabled": staticmethod(lambda: True),
        "get_trace_row": staticmethod(lambda *a: {"rule_name": "Link Purpose", "level": "A",
                                                  "detail": "", "finding_count": 1,
                                                  "severity": ""}),
        "get_issue_rule_ids": staticmethod(lambda *a: [])})())
    monkeypatch.setattr(ai, "explain_finding", lambda **k: None)      # the call failed
    monkeypatch.setattr(ai, "suggest_fix", lambda **k: None)

    code, detail = _detail(rai.ai_explain, scan_id="s1", file="p.docx", rule_id="2.4.4")
    assert code == 503 and MARKER not in detail

    code, detail = _detail(rai.ai_suggest, request=object(), scan_id="s1", file="p.docx",
                           rule_id="2.4.4")
    assert code == 503 and MARKER not in detail


def test_deterministic_only_mode_is_a_403_and_not_marked(ollama_only, monkeypatch):
    """An admin switching AI off is a policy decision, not a missing model."""
    monkeypatch.setattr(core, "store", type("S", (), {
        "get_ai_enabled": staticmethod(lambda: False)})())
    code, detail = _detail(rai.ai_suggest, request=object(), scan_id="s1", file="p.docx",
                           rule_id="2.4.4")
    assert code == 403 and MARKER not in detail
