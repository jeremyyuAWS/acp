"""The criterion-disposition counts in docs/TODO.md, and the ways they could lie.

WHY THIS FILE EXISTS. The counts used to be a hand-maintained table carrying 36 / 45 / 6, with
the doc's own instruction to "treat them as 2026-07-09 figures until someone re-counts against
the catalog" — because `frontend/src/wcagCatalog.js` was not in the checkout when that paragraph
was written. The catalog arrived on 2026-08-28 (#907) and nobody re-counted; the real split was
37 / 44 / 6. One criterion had moved from HITL to shipped and the table could not say so.

Moving the counts into `gen_todo_status.py` stops them drifting. It introduces a different
failure, which is what these tests are for: the counts come from a REGEX over a JavaScript file,
and a regex that stops matching does not error — it returns nothing, and every bucket renders as
zero. A coverage table reading "Shipped: 0" is a worse lie than one reading "36", because it is
the kind of number a reader assumes must be a bug somewhere else.
"""
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "frontend" / "src" / "wcagCatalog.js"
TODO = ROOT / "docs" / "TODO.md"

_spec = importlib.util.spec_from_file_location(
    "gen_todo_status", ROOT / "scripts" / "gen_todo_status.py")
gen = importlib.util.module_from_spec(_spec)
sys.modules["gen_todo_status"] = gen
_spec.loader.exec_module(gen)


def test_the_catalog_is_actually_present():
    """The premise. TODO.md said this file was absent for long enough that its counts went stale,
    so its absence is the first thing worth failing on rather than parsing to zero."""
    assert CATALOG.exists(), (
        f"{CATALOG.relative_to(ROOT)} is gone — the disposition counts in docs/TODO.md have no "
        f"source, and gen_todo_status will fail rather than render zeros")


def test_every_criterion_in_the_catalog_is_counted():
    """ANTI-VACUOUS, and the whole reason the generator cross-checks its own parse.

    `catalog_counts()` matches `sc:` and `source:` in one pattern. If the catalog's formatting
    changes — a reordered field, a line break between them — the pattern matches fewer rows and
    silently under-counts. This compares the parse against an independent count of the `sc:` keys,
    which is the same check the generator raises SystemExit on.
    """
    counts = gen.catalog_counts()
    declared = len(re.findall(r'\{sc:"[\d.]+"', CATALOG.read_text(encoding="utf-8")))
    assert declared > 0, "no criteria found at all — the sc: pattern has drifted"
    assert sum(counts.values()) == declared, (
        f"the parse found {sum(counts.values())} sources for {declared} criteria — it is "
        f"under-counting, and the rendered table would understate coverage")


def test_the_generator_refuses_rather_than_rendering_a_short_count(monkeypatch):
    """THE BITE CHECK, kept as a test because the failure it guards is silent by nature.

    A parse that goes short renders a smaller table, and a smaller coverage table reads as bad
    news about the product rather than as a broken regex. The generator raises instead.
    """
    monkeypatch.setattr(gen, "catalog_counts", lambda: {"Shipped (demo)": 1})
    with pytest.raises(SystemExit, match="regex has drifted"):
        gen.build(*gen._load())


def test_the_buckets_are_the_catalogs_own():
    """A bucket the doc does not describe is rendered with a loud placeholder rather than
    dropped — dropping it would make the table's total disagree with the criterion count while
    every row still looked reasonable."""
    counts = gen.catalog_counts()
    assert set(counts) <= set(gen.CATALOG_BUCKETS), (
        f"the catalog has a `source:` value this file does not describe: "
        f"{sorted(set(counts) - set(gen.CATALOG_BUCKETS))}. The generator renders it with a "
        f"placeholder; add it to CATALOG_BUCKETS with what it means.")


def test_the_rendered_table_carries_the_real_numbers():
    """End to end: what the generator computes is what the committed document says."""
    counts = gen.catalog_counts()
    text = TODO.read_text(encoding="utf-8")
    for bucket, n in counts.items():
        assert f"| {bucket} | {n} |" in text, (
            f"docs/TODO.md does not carry `{bucket} = {n}` — run "
            f"`python scripts/gen_todo_status.py`")


def test_the_authored_half_no_longer_carries_a_hand_count():
    """The old table lived above the markers, where nothing could check it. If a hand-maintained
    count reappears there it will drift again, and this is the notice."""
    text = TODO.read_text(encoding="utf-8")
    authored = text[: text.index("<!-- BEGIN GENERATED: coverage-status")]
    assert "| Shipped (demo) |" not in authored, (
        "a hand-maintained disposition table is back in the authored half of docs/TODO.md — the "
        "generated block below is the one that cannot go stale")
