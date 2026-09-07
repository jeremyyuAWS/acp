"""The Claude rows of providers._PRICE_PER_1M are real list prices, and one of them was not.

`_PRICE_PER_1M` is not a display table. Its numbers are multiplied by the token counts the API
returns to produce the `ai_calls` cost, and that cost is what `remediation_pilot`'s
`max_spend_usd` guard adds up — so a wrong row is a wrong spend cap, and ADR 0016's rule against
fabricated numbers applies to it directly.

`claude-sonnet-5` carried `(3.00, 15.00)`, which is **Sonnet 4.6's** price: a generation's number
attached to its successor's name when the id was added. Sonnet 5 is `(2.00, 10.00)`. It
over-quoted by 50%, so the guard stopped early rather than late — the safe direction, by luck
rather than design.

WHY THE WHOLE TABLE IS PINNED AND NOT JUST THE ONE ROW. The defect was not arithmetic; it was a
price surviving a model it no longer described. Only a check that names every model can catch the
next one, and the next one arrives whenever a model id is added by copying the line above it.

These are Anthropic first-party list prices per 1M tokens (input, output). Bedrock and Vertex are
partner-operated and priced separately — this table is only ever used for first-party calls, and
a partner row would need its own source.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

# Anthropic first-party list prices, USD per 1M tokens: (input, output).
CLAUDE_LIST_PRICES = {
    "claude-fable-5": (10.00, 50.00),
    "claude-opus-5": (5.00, 25.00),
    "claude-opus-4-8": (5.00, 25.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-haiku-4-5": (1.00, 5.00),
}


@pytest.mark.parametrize("model,expected", sorted(CLAUDE_LIST_PRICES.items()))
def test_each_claude_row_is_its_own_models_list_price(model, expected):
    import providers
    assert providers._PRICE_PER_1M[model] == expected, (
        f"{model} is priced at {providers._PRICE_PER_1M[model]}, not {expected}. This number is "
        "multiplied by real token counts to produce the ai_calls cost that remediation_pilot's "
        "max_spend_usd guard sums, so it is a billing input, not a label.")


def test_sonnet_5_is_not_priced_as_sonnet_4_6():
    """The specific regression, named so it cannot come back quietly.

    Sonnet 4.6 is (3.00, 15.00) and Sonnet 5 is (2.00, 10.00). The two ids differ by three
    characters and the prices look equally plausible beside each other, which is exactly how the
    wrong one survived.
    """
    import providers
    assert providers._PRICE_PER_1M["claude-sonnet-5"] != (3.00, 15.00), (
        "claude-sonnet-5 is priced at Sonnet 4.6's rate again")


def test_the_lookup_is_substring_based_so_a_dated_id_still_prices():
    """`_price_for` matches by substring, which is what lets a suffixed id resolve — and is also
    why every key must stay a full version id. A key of 'claude-sonnet' would swallow every
    Sonnet generation at one price, which is the same defect this file exists for, generalised."""
    import providers
    assert providers._price_for("claude-sonnet-5") == (2.00, 10.00)
    assert providers._price_for("claude-opus-5") == (5.00, 25.00)
    # An unknown model prices at nothing rather than at a guess — the table's own stated contract.
    assert providers._price_for("some-model-we-have-never-seen") is None


def test_no_claude_row_is_missing_from_the_pin():
    """If a Claude model is added to the table, it must be added here too — with its real price
    looked up, not copied from the neighbouring line, which is how this defect was born."""
    import providers
    in_table = {k for k in providers._PRICE_PER_1M if k.startswith("claude-")}
    unpinned = in_table - set(CLAUDE_LIST_PRICES)
    assert not unpinned, (
        f"unpinned Claude model(s) in _PRICE_PER_1M: {sorted(unpinned)}. Add them here with the "
        "list price from Anthropic's pricing page, not from the line above them in the table.")
