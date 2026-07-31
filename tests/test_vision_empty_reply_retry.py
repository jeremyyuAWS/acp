"""A vision model that replies with NOTHING must not read as "the feature is off".

Measured 2026-07-31 against the deployed endpoint (moondream, the CPU deploy default): the full
`_vision_prompt` came back HTTP 200 with `{"response": "", "done_reason": "stop"}` — no error, no
exception, just nothing — so `describe_image` returned None and the reviewer's re-draft (#131) did
nothing at all when clicked. Vision was configured correctly and the model was fine; the prompt was
the bug.

Three separate things each triggered the empty reply on their own, which is why shortening the
prompt was not the fix:

  "Describe this image in one concise sentence under 30 words."  → a real description
  …plus a trailing "\\nAlt text:" label                          → EMPTY
  …plus "Do not begin with image of."                           → EMPTY
  a longer multi-clause instruction, neither of those           → EMPTY

So the full prompt is kept for models that handle it (and write better alt text for it), and a bare
retry covers the compact ones.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

import ai as _ai  # noqa: E402


def test_describe_image_retries_bare_when_the_model_returns_nothing(monkeypatch):
    """The regression: first prompt yields nothing, so a second, barer one is tried."""
    prompts = []

    def fake_generate(prompt, image_bytes, **_):
        prompts.append(prompt)
        return None if len(prompts) == 1 else "A quarterly revenue report slide."

    monkeypatch.setattr(_ai, "_vision_generate", fake_generate)
    out = _ai.describe_image(b"PNGBYTES", filename="deck.pptx")

    assert out is not None, "an empty first reply must not end as None — that is the dead button"
    assert out["alt"] == "A quarterly revenue report slide."
    assert len(prompts) == 2
    assert prompts[0] != prompts[1]
    # The retry is the bare form, not a re-send of the prompt the model just refused.
    assert prompts[1] == _ai._minimal_vision_prompt("")


def test_a_working_model_is_asked_exactly_once(monkeypatch):
    """No retry when the first reply is usable — the full prompt's answer is the better one."""
    prompts = []

    def fake_generate(prompt, image_bytes, **_):
        prompts.append(prompt)
        return "A bar chart comparing revenue across regions."

    monkeypatch.setattr(_ai, "_vision_generate", fake_generate)
    out = _ai.describe_image(b"PNGBYTES", filename="deck.pptx")

    assert out["alt"] == "A bar chart comparing revenue across regions."
    assert len(prompts) == 1


def test_both_attempts_failing_still_returns_none(monkeypatch):
    """A genuinely unavailable model still degrades to None — callers fall back as before."""
    monkeypatch.setattr(_ai, "_vision_generate", lambda *a, **k: None)
    assert _ai.describe_image(b"PNGBYTES", filename="deck.pptx") is None


def test_the_retry_carries_the_reviewers_length_steer(monkeypatch):
    """#131's 'shorter'/'detailed' must survive the retry, or re-draft silently ignores the choice."""
    for style in ("shorter", "detailed", ""):
        prompts = []

        def fake_generate(prompt, image_bytes, **_):
            prompts.append(prompt)
            return None if len(prompts) == 1 else "Some alt text."

        monkeypatch.setattr(_ai, "_vision_generate", fake_generate)
        _ai.describe_image(b"PNGBYTES", filename="deck.pptx", style=style)
        assert prompts[1] == _ai._minimal_vision_prompt(style)

    assert _ai._minimal_vision_prompt("shorter") != _ai._minimal_vision_prompt("detailed")


def test_minimal_vision_prompt_stays_bare():
    """The three measured triggers, guarded. Each one alone empties a compact model's reply."""
    for style in ("", "shorter", "detailed"):
        p = _ai._minimal_vision_prompt(style)
        assert "\n" not in p, f"{style!r}: a trailing label/newline empties the reply"
        assert not p.rstrip().endswith(":"), f"{style!r}: must not end on a label like 'Alt text:'"
        assert "do not" not in p.lower(), f"{style!r}: a negation empties the reply"
        assert "never" not in p.lower(), f"{style!r}: a negation empties the reply"
        assert len(p) <= 120, f"{style!r}: {len(p)} chars — keep the retry short"
        assert p.lower().startswith("describe this image")
