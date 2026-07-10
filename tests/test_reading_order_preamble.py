"""A reading-order proposal should be a reading order, not the model clearing its throat.

Verbatim from llava:7b, run against the real patient-discharge-instructions.pdf:

    "The image shows a document with text and graphics. To provide an accurate reading order
     for this page, I would describe the content in a linear fashion from top to bottom:
     1. Logo at the top left corner 2. Title 3. ..."

The reviewer's card renders that string AS the proposed reading order. When the model
enumerates, the enumeration is the answer; when it doesn't, the prose is all we have and must
survive untouched. No prompt was changed — this is a deterministic trim of the response.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))
from ai import _strip_order_preamble as strip  # noqa: E402

REAL = ("The image shows a document with text and graphics. To provide an accurate reading "
        "order for this page, I would describe the content in a linear fashion from top to "
        "bottom: 1. Logo at the top left corner 2. Title 3. Medication list")


def test_the_real_llava_response_is_trimmed_to_its_list():
    out = strip(REAL)
    assert out.startswith("1. Logo at the top left corner")
    assert "The image shows" not in out
    assert "3. Medication list" in out


def test_a_list_that_starts_at_the_beginning_is_untouched():
    s = "1. Header 2. Left column 3. Footer"
    assert strip(s) == s


def test_parenthesised_enumerators_are_recognised():
    assert strip("Here is the order: 1) Title 2) Body").startswith("1) Title")


def test_prose_with_no_enumeration_survives_untouched():
    # The model is allowed to answer in a sentence. That IS the answer; do not mangle it.
    s = "Read the left column top to bottom, then the right column, then the footer."
    assert strip(s) == s


def test_a_trailing_enumerator_with_nothing_after_it_is_not_an_answer():
    # No \S after "1." -> the pattern must not match at all.
    s = "The page has a single column. See figure 1."
    assert strip(s) == s


def test_an_enumerated_item_too_short_to_be_an_order_is_refused():
    # This one exercises the length guard: the trim WOULD match, and would leave "1. x".
    # Returning that is worse than the sentence it replaced, so the original survives.
    s = "The reading order is simply: 1. x"
    assert strip(s) == s
    assert strip("Order: 1. Header then the body text") == "1. Header then the body text"


def test_a_year_or_measurement_is_not_mistaken_for_an_enumerator():
    s = "The header shows 2026 revenue and a 1.4 percent margin, then the table."
    assert strip(s) == s


def test_empty_and_none_are_safe():
    assert strip("") == ""
    assert strip(None) is None


def test_it_never_lengthens_or_invents():
    for s in [REAL, "1. A 2. B", "prose only", ""]:
        assert len(strip(s)) <= len(s)
        assert strip(s) in s or strip(s) == s


# ── the trim is actually wired into the response path ──

def test_describe_reading_order_applies_the_trim(monkeypatch):
    """Asserting on the helper alone is vacuous: unhooking it from describe_reading_order
    left every test above green. Drive the real function with a canned model response."""
    import ai

    class _Resp:
        @staticmethod
        def raise_for_status():
            pass

        @staticmethod
        def json():
            return {"response": REAL}

    import httpx
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _Resp())   # ai.py imports httpx in-function
    monkeypatch.setattr(ai, "_trace_ai", lambda *a, **k: None)
    out = ai.describe_reading_order(b"\x89PNG-not-really", filename="p.pdf")
    assert out is not None
    assert out["order"].startswith("1. Logo at the top left corner")
    assert "The image shows" not in out["order"]


def test_describe_reading_order_leaves_prose_alone(monkeypatch):
    import ai
    prose = "Read the left column top to bottom, then the right column, then the footer."

    class _Resp:
        @staticmethod
        def raise_for_status():
            pass

        @staticmethod
        def json():
            return {"response": prose}

    import httpx
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _Resp())
    monkeypatch.setattr(ai, "_trace_ai", lambda *a, **k: None)
    assert ai.describe_reading_order(b"x", filename="p.pdf")["order"] == prose
