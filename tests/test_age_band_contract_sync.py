"""The age-band keys are a contract between two languages, and nothing was checking it.

`AGE_BANDS` lives in api/estate_inventory.py and decides the keys in `summarize()["by_age"]`.
`AGE_ORDER` lives in frontend/src/estateFunnel.js and decides which of those keys get rendered,
in which order, with which label.

Neither side's tests can see the other. The frontend cases pin hardcoded keys against a hand-built
fixture; the backend cases assert only that emitted keys are a subset of its own declaration. So a
rename on either side passes both suites and produces an EMPTY PANEL in production — `ageRows`
filters on keys that no longer exist, returns nothing, and the panel is designed to render nothing
when there is no data. The failure would look exactly like "this scan has no age data", which is a
legitimate state.

That is the shape that broke #471: a Python guard regex-matching a JS constant, where moving the
constant made the guard parse zero and the two sides disagreed silently. Same trap, other direction.

This repo already answers it this way — tests/test_assess_coverage_contract_sync.py reads the JS
rather than restating it. So does this.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

from estate_inventory import AGE_BANDS, AGE_UNKNOWN  # noqa: E402

_FUNNEL_JS = (ACP / "frontend" / "src" / "estateFunnel.js").read_text()


def _js_age_order() -> list[str]:
    m = re.search(r"const AGE_ORDER\s*=\s*\[(.*?)\]", _FUNNEL_JS, re.S)
    assert m, "AGE_ORDER not found in estateFunnel.js — the age panel's key list moved."
    return re.findall(r"'([a-z0-9_]+)'", m.group(1))


def _js_age_labels() -> dict[str, str]:
    m = re.search(r"const AGE_LABEL\s*=\s*\{(.*?)\n\}", _FUNNEL_JS, re.S)
    assert m, "AGE_LABEL not found in estateFunnel.js."
    return dict(re.findall(r"(\w+):\s*'([^']*)'", m.group(1)))


def test_the_frontend_renders_exactly_the_bands_the_backend_emits():
    """A key on one side and not the other is a band that silently never renders, or a labelled
    bucket that never arrives. Both read as "no age data", which is a legitimate state — so neither
    would look like a bug."""
    backend = [key for key, _label, _upper in AGE_BANDS] + [AGE_UNKNOWN]
    assert _js_age_order() == backend, (
        "AGE_ORDER (estateFunnel.js) and AGE_BANDS (estate_inventory.py) disagree. A band missing "
        "from the JS is dropped from the panel with no error; one missing from Python renders "
        "nothing. Update both."
    )


def test_every_rendered_band_has_a_label():
    """An unlabelled band falls back to its raw key — 'y1_3' on screen beside a bar."""
    labels = _js_age_labels()
    for key in _js_age_order():
        assert key in labels and labels[key].strip(), f"no AGE_LABEL for {key!r}"


def test_unknown_is_last_because_it_is_the_caveat_on_every_other_bar():
    """Ordinal buckets, youngest first; the files with no date qualify the rest and belong at the
    end rather than sorted in among them."""
    order = _js_age_order()
    assert order[-1] == AGE_UNKNOWN
    assert order[0] == AGE_BANDS[0][0]
