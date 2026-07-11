"""The normalized {result, provenance, trust} envelope (ADR 0019 §3b).

A pure assembler that must never mutate `result` and must stay honest: local build → processing_zone
'local', cost 0; every field a measurement or an evidence flag, never a fabricated score.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))
import ai  # noqa: E402


def test_result_passes_through_untouched():
    r = {"alt": "A bar chart.", "kind": "alt text"}
    env = ai.build_envelope(r, model="llava:13b", grounded=True, grounding_sources=["chart_labels"])
    assert env["result"] is r                        # callers keep reading exactly what they passed
    assert env["result"]["alt"] == "A bar chart."


def test_local_build_is_honest_zone_and_zero_cost():
    env = ai.build_envelope({"alt": "x"}, latency_ms=1800.0)
    prov = env["provenance"]
    # The keyless Ollama build never leaves the box; the envelope must say so and cost nothing.
    assert prov["processing_zone"] == "local"
    assert prov["cost_usd"] == 0.0
    assert prov["provider"] == "ollama"
    assert prov["latency_ms"] == 1800.0


def test_trust_carries_grounding_not_a_number():
    env = ai.build_envelope({"alt": "x"}, grounded=False)
    assert env["trust"]["grounded"] is False
    assert env["trust"]["grounding_sources"] == []
    # No percentage / confidence score anywhere in the envelope (ADR 0016).
    import json
    assert "%" not in json.dumps(env)
    assert "confidence" not in json.dumps(env).lower()
