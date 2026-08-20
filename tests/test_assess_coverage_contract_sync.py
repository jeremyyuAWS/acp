"""Contract: the estate rollups pinned in the FRONTEND coverage test must still follow from
the BACKEND assessment table.

frontend/src/assessCoverage.test.js hardcodes, per format, how the 20-check document core
partitions into 🟢/🟡/🔴/gap/at/⚪. Those totals are a deliberate snapshot — a lane change
should have to be acknowledged, not absorbed silently. But they are hand-maintained numbers in
the JS suite, derived from a table whose source of truth is Python
(remediation_capability.assessment_table()). That split is how 997b7d0 reached main red:

  - it moved docx 2.4.6 🟢 -> 🟡 in api/remediation_capability.py, correctly,
  - mirrored it into frontend/src/capability.js, correctly,
  - and never touched the JS test that pins the totals computed from it.

`pytest` was green the whole time, because nothing on this side of the language boundary knew
the frontend had a stake in that number. The existing guard, tests/test_capability_frontend_sync.py,
locks the JS TABLE to the Python table and stops there — one link short of the totals.

So this recomputes the rollups from the PYTHON table (not the JS mirror, so a lane change fails
here the moment it lands, before capability.js is even updated) and asserts they equal the
numbers the frontend test pins. When it fails, the assessment table moved and
frontend/src/assessCoverage.test.js needs its EST block updated to match.

Every constant is READ from the JS rather than restated here — DOCUMENTS_20, the REVIEW_ONLY /
GAP / AT overlays, and the EST literal itself. The only thing reimplemented is assessmentIn's
six-line precedence rule; if that rule changes in JS this guard goes stale, which is why the
precedence is asserted against a known cell below rather than trusted silently.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

import remediation_capability as cap  # noqa: E402

_COVERAGE_JS = (ACP / "frontend" / "src" / "assessCoverage.js").read_text()
_TEST_JS = (ACP / "frontend" / "src" / "assessCoverage.test.js").read_text()
# The 20-core moved to its own module. assessCoverage.js now re-exports it rather than restating
# it, which is the point of that change — one hand-maintained list instead of two that can drift.
_DOCUMENTS_20_JS = (ACP / "frontend" / "src" / "documents20.js").read_text()

# Buckets assessmentIn can return, in the order the frontend test lists them.
_BUCKETS = ("auto", "review", "human", "gap", "at", "na")


def _documents_20() -> list[str]:
    """The 20-check document core, read from its canonical module.

    This used to parse an array literal out of assessCoverage.js. That literal is gone: it was a
    second, hand-maintained copy of documents20.js's Set, one edit from disagreeing with the
    activeScope CORE_SCS the rest of the page counts against, and it now derives from the Set
    instead. Parsing the source of truth is what this guard always meant to do — the docstring
    above says every constant is READ from the JS rather than restated here — so it follows the
    constant rather than pinning the file it used to live in.
    """
    m = re.search(r"export const DOCUMENTS_20\s*=\s*new Set\(\s*\[(.*?)\]\s*\)",
                  _DOCUMENTS_20_JS, re.S)
    assert m, "DOCUMENTS_20 set not found in documents20.js — the canonical 20-core module moved."
    scs = re.findall(r"'([\d.]+)'", m.group(1))
    assert len(scs) == 20, f"DOCUMENTS_20 should hold 20 criteria, parsed {len(scs)}"

    # And assessCoverage.js must still DERIVE from that Set. Without this, re-inlining a divergent
    # literal there would leave this guard reading the canonical file, passing, and asserting
    # nothing about the list the coverage module actually iterates — the exact drift the move was
    # made to prevent, now invisible.
    assert re.search(r"export const DOCUMENTS_20\s*=\s*\[\s*\.\.\.\s*DOCUMENTS_20_CORE\s*\]",
                     _COVERAGE_JS), (
        "assessCoverage.js no longer derives DOCUMENTS_20 from documents20.js — if it restates "
        "the list again, the two can drift and this guard would not see it.")
    return scs


def _js_set(name: str) -> set[str]:
    """A `const NAME = new Set([...])` of 'sc|fmt' keys. Comments inside are ignored because
    only quoted entries are matched. An empty `new Set()` yields an empty set."""
    m = re.search(rf"const {name}\s*=\s*new Set\(\s*\[(.*?)\]\s*\)", _COVERAGE_JS, re.S)
    if m is None:
        assert re.search(rf"const {name}\s*=\s*new Set\(\s*\)", _COVERAGE_JS), (
            f"{name} set not found in assessCoverage.js — the overlay moved.")
        return set()
    return set(re.findall(r"'([^']+)'", m.group(1)))


def _pinned_estates() -> dict[str, dict[str, int]]:
    """The `const EST = { docx: { auto: N, ... }, ... }` literal from the frontend test."""
    m = re.search(r"const EST\s*=\s*\{(.*?)\n  \}", _TEST_JS, re.S)
    assert m, ("the EST estate block was not found in assessCoverage.test.js — the frontend "
               "coverage contract moved; update this guard.")
    out: dict[str, dict[str, int]] = {}
    for fmt, fields in re.findall(r"(\w+):\s*\{([^}]*)\}", m.group(1)):
        out[fmt] = {k: int(v) for k, v in re.findall(r"(\w+):\s*(\d+)", fields)}
    assert out, "no estates parsed out of the EST block"
    return out


def _assessment_in(sc: str, fmt: str, table, review_only, gap, at) -> str:
    """assessCoverage.js `assessmentIn`, in Python. Table verdict wins; then the controls-gated
    review overlay; then buildable-gap; then assistive-tech-only; else the criterion cannot
    exist in this format (⚪ na)."""
    a = table.get(fmt, {}).get(sc)
    if a in ("auto", "review", "human"):
        return a
    key = f"{sc}|{fmt}"
    if key in review_only:
        return "review"
    if key in gap:
        return "gap"
    if key in at:
        return "at"
    return "na"


def _rollup(fmt: str, table) -> dict[str, int]:
    scs, review_only, gap, at = _documents_20(), _js_set("REVIEW_ONLY"), _js_set("GAP"), _js_set("AT")
    counts = dict.fromkeys(_BUCKETS, 0)
    for sc in scs:
        counts[_assessment_in(sc, fmt, table, review_only, gap, at)] += 1
    return counts


def test_reimplemented_precedence_matches_a_known_cell():
    """Pin the rule this guard reimplements, so a precedence change in JS surfaces here as a
    precedence failure rather than as a confusing count mismatch."""
    table, review_only = cap.assessment_table(), _js_set("REVIEW_ONLY")
    gap, at = _js_set("GAP"), _js_set("AT")
    # table verdict wins outright
    assert _assessment_in("1.4.3", "docx", table, review_only, gap, at) == "auto"
    # 2.4.6 on docx is 🟡 since 997b7d0 — the cell this whole guard exists because of
    assert _assessment_in("2.4.6", "docx", table, review_only, gap, at) == "review"
    # absent from the table, present in the controls-gated overlay
    assert "4.1.2|docx" in review_only
    assert _assessment_in("4.1.2", "docx", table, review_only, gap, at) == "review"
    # in neither → the barrier cannot exist in this format
    assert _assessment_in("2.4.3", "docx", table, review_only, gap, at) == "na"


def test_frontend_estate_rollups_follow_from_the_backend_assessment_table():
    table = cap.assessment_table()
    offenders = []
    for fmt, pinned in _pinned_estates().items():
        got = _rollup(fmt, table)
        want = {k: v for k, v in pinned.items() if k in _BUCKETS}
        if got != want:
            diff = ", ".join(f"{k}: pinned {want[k]} vs table {got[k]}"
                             for k in _BUCKETS if want.get(k) != got.get(k))
            offenders.append(f"  {fmt}: {diff}")
    assert not offenders, (
        "frontend/src/assessCoverage.test.js pins estate totals that no longer follow from "
        "api/remediation_capability.py assessment_table():\n" + "\n".join(offenders)
        + "\n\nA lane moved on the backend and the frontend coverage contract still describes "
          "the old shape. Update the EST block in assessCoverage.test.js (and re-check the "
          "mixed-estate and union assertions below it, which are computed from the same table).")


def test_certifiable_is_the_auto_bucket_and_the_partition_is_total():
    """The two invariants the frontend test asserts per estate, checked against the backend
    table so they cannot rot in step with a stale pin."""
    table = cap.assessment_table()
    for fmt, pinned in _pinned_estates().items():
        got = _rollup(fmt, table)
        assert sum(got.values()) == 20, f"{fmt}: buckets sum to {sum(got.values())}, not 20"
        if "certifiable" in pinned:
            assert pinned["certifiable"] == got["auto"], (
                f"{fmt}: certifiable is pinned at {pinned['certifiable']} but the honest "
                f"headline is the 🟢 bucket only, which the table puts at {got['auto']}")
