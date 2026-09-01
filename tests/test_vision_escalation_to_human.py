"""Escalation, and what happens when it fails (ADR 0019 §2/§3c).

THE CONTRACT, in one line: a local description that could not be grounded MAY escalate to a
customer-enabled cloud provider, and when that escalation does not produce something usable the
proposal comes back to a HUMAN — it never auto-applies and never dresses a failure as a result.

Three states have to stay distinguishable in the returned dict, because the reviewer UI treats
them differently and because two of them look identical if you only check `alt`:

    grounded=True                OCR read real text from the image. High confidence.
    grounded=False, escalation   a cloud model produced a description the local one could not.
                                 Still for confirmation — a stronger guess is still a guess.
    grounded=False, no escalation the local model's own guess, or nothing at all.

The escalation path is opt-in by construction: with no cloud provider configured and enabled,
cloud_vision_provider() returns None, _escalate_vision returns None immediately, and no bytes
leave the network. That is the out-of-box state and the first test here.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))


@pytest.fixture()
def local_says_nothing_useful(monkeypatch):
    """The situation the whole feature exists for: OCR finds no text (so nothing can ground) and
    the local vision model returns a caption too thin for WCAG 1.1.1."""
    import ai
    monkeypatch.setattr(ai, "_ocr_text", lambda *a, **k: "", raising=False)
    monkeypatch.setattr(ai, "_vision_generate",
                        lambda *a, **k: {"text": "", "ok": False, "model": "moondream"},
                        raising=False)
    return ai


def _cloud(text="A quarterly revenue chart with four rising bars labelled Q1 to Q4.",
           *, ok=True, provider="anthropic", cost=0.0031):
    class _P:
        name, zone = provider, "cloud"

        def generate(self, prompt, image_bytes, *, model=None, timeout=120.0):
            return {"text": text, "ok": ok, "model": "claude-sonnet-5", "provider": provider,
                    "zone": "cloud", "latency_ms": 900, "cost_usd": cost,
                    "reason": "ok" if ok else "http_401",
                    "prompt_tokens": 1200, "completion_tokens": 40}
    return _P()


def test_with_no_provider_enabled_nothing_escalates_and_nothing_leaves(monkeypatch,
                                                                      local_says_nothing_useful):
    """The keyless local build. cloud_vision_provider() is the single gate, and it is None until
    an admin both configures AND enables a provider whose secret resolves."""
    import ai
    import providers
    monkeypatch.setattr(providers, "cloud_vision_provider", lambda: None)
    calls = []
    monkeypatch.setattr(providers, "_adapter_for", lambda *a, **k: calls.append(a) or None)

    assert ai._escalate_vision("prompt", b"\x89PNG", scan_id="s1", file="f.docx") is None
    assert calls == []                        # no adapter was even built, so no bytes could go


def test_an_ungrounded_local_description_escalates_to_the_enabled_provider(monkeypatch,
                                                                          local_says_nothing_useful):
    import ai
    import providers
    monkeypatch.setattr(providers, "cloud_vision_provider", lambda: _cloud())
    monkeypatch.setattr(ai, "_trace_ai", lambda *a, **k: None)

    esc = ai._escalate_vision("prompt", b"\x89PNG", scan_id="s1", file="f.docx")
    assert esc is not None
    assert esc["provider"] == "anthropic" and esc["zone"] == "cloud"
    assert esc["cost_usd"] == 0.0031
    # The numbered path is TRANSPARENT — the reviewer is told the local model went first and
    # what it produced, not handed a cloud answer as though it were the only one.
    assert [s["outcome"] for s in esc["steps"]] == ["no grounded description",
                                                    "produced a description"]
    assert esc["steps"][0]["provider"] == "ollama"
    assert esc["steps"][1]["provider"] == "anthropic"


def test_the_escalated_call_is_traced_with_its_real_usage_and_cost(monkeypatch,
                                                                  local_says_nothing_useful):
    """A cloud call that is not recorded is a cost and a disclosure nobody can audit. It goes
    through the same ai_calls provenance path as every local call, carrying the real token
    counts and the real cost — which is what makes /ai/costs able to report them."""
    import ai
    import providers
    monkeypatch.setattr(providers, "cloud_vision_provider", lambda: _cloud())
    traced = {}
    monkeypatch.setattr(ai, "_trace_ai", lambda *a, **k: traced.update(k))

    ai._escalate_vision("prompt", b"\x89PNG", scan_id="s1", file="f.docx")
    assert traced["provider"] == "anthropic" and traced["zone"] == "cloud"
    assert traced["cost_usd"] == 0.0031
    assert traced["prompt_tokens"] == 1200 and traced["completion_tokens"] == 40
    assert traced["ok"] is True and traced["scan_id"] == "s1" and traced["file"] == "f.docx"


# ── escalation FAILS → back to a human ────────────────────────────────────────────────────────

@pytest.mark.parametrize("cloud,why", [
    (lambda: _cloud(ok=False, text=None), "the cloud call failed (a bad key, a dead route)"),
    (lambda: _cloud(text=""), "the cloud model answered with nothing"),
    (lambda: _cloud(text="chart"), "the answer was too thin to certify from"),
    (lambda: None, "no provider is enabled"),
])
def test_when_escalation_cannot_produce_something_usable_it_returns_none(
        monkeypatch, local_says_nothing_useful, cloud, why):
    """Every failure mode collapses to None, which is what sends the file back to human review.

    Returning a partial or a placeholder would be worse than returning nothing: the caller treats
    a truthy result as a description a reviewer can confirm, so 'chart' would reach the queue
    looking like an answer. The honesty guard (len >= 8 and a space) is what stops that, and it
    is why the third case here is a FAILURE and not a success.
    """
    import ai
    import providers
    monkeypatch.setattr(providers, "cloud_vision_provider", cloud)
    monkeypatch.setattr(ai, "_trace_ai", lambda *a, **k: None)
    assert ai._escalate_vision("prompt", b"\x89PNG") is None, why


def test_a_failed_escalation_leaves_the_local_evidence_line_for_the_reviewer(monkeypatch):
    """The user-visible half. When escalation does not fire or does not help, the result must
    still say plainly that this is an unanchored guess needing confirmation — not silently adopt
    the cloud wording, and not go quiet about which path ran."""
    import ai
    import providers
    monkeypatch.setattr(providers, "cloud_vision_provider", lambda: None)
    monkeypatch.setattr(ai, "_ocr_text", lambda *a, **k: "", raising=False)
    monkeypatch.setattr(ai, "_vision_generate",
                        lambda *a, **k: {"text": "A photograph of a person at a desk.",
                                         "ok": True, "model": "moondream"}, raising=False)
    monkeypatch.setattr(ai, "_trace_ai", lambda *a, **k: None)

    out = ai.describe_image_structured(b"\x89PNG-not-really", filename="photo.png")
    if out is None:
        pytest.skip("the local path declined before evidence was built — covered by ai's own tests")
    assert out["grounded"] is False
    assert "escalation" not in out                       # nothing to disclose: none happened
    assert "confirm it matches the intent" in out["evidence"]
    # It must NOT claim a cloud model helped when none did.
    assert "cloud" not in out["evidence"]
