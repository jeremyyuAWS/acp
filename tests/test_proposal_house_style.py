"""ADR 0021 §E — the "house style applied" chip on a SCAN-TIME pre-drafted card.

#999 put the chip on drafts from the live `/ai/suggest` path. A card whose value arrived
pre-drafted during the scan showed nothing, because `handlers._propose_text_findings` injected
house style into those prompts and recorded nowhere which rules it used. This closes that.

THE ASSERTION THAT MATTERS IS THE NEGATIVE ONE. `_enqueue_proposals` is the choke point for 12
criteria and is the obvious place to stamp — one function, every call site, the same argument the
operator-scope gate makes for living there. It is the WRONG place, and stamping there would have
been a bug that looked like good coverage: only five of those criteria are handed guidance at
all. Reading order, the colour and contrast cards, the one-click layout fixes, chart datasheets
and the language tags are deterministic, and ADR 0021 excludes them by name —

    Deterministic proposers (chart datasheet, language tag, the one-click layout cards) ignore
    memory — there is nothing to steer.

A chip on those cards would assert an influence that never happened, on a value a human is about
to certify. That is the precise failure the chip exists to prevent, so the tests below spend more
effort on where the chip must NOT appear than on where it must.

The stamp rides inside the existing `proposals` JSON blob — no schema change:
`store._decode_proposals` is a plain `json.loads` and `routes/hitl.py` returns rows unfiltered,
so an extra key reaches the SPA intact.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

import handlers  # noqa: E402

RULE = {"id": "r1", "kind": "style", "guidance": "Keep link text verb-first.",
        "rule_id": "2.4.4", "format": None, "evidence": None}
PROPOSALS = [{"locator": "l1", "before": "click here", "proposed_value": "Read the policy"},
             {"locator": "l2", "before": "more", "proposed_value": "See the schedule"}]


@pytest.fixture
def enqueued(monkeypatch):
    """Capture what reaches store.enqueue_proposals, with the scope gate open."""
    seen: list[dict] = []
    monkeypatch.setattr(handlers, "_remediation_scope", lambda *a, **kw: None)
    monkeypatch.setattr(handlers.core, "store", type("S", (), {
        "enqueue_proposals": staticmethod(
            lambda scan_id, file, sc, proposals, **kw: seen.append(
                {"sc": sc, "proposals": proposals, **kw}) or "id1"),
    })())
    return seen


# ── the stamp lands, and carries the real rules ──────────────────────────────────

def test_house_style_is_stamped_on_every_proposal(enqueued):
    handlers._enqueue_proposals("s1", "f.docx", "2.4.4", "Link Purpose", PROPOSALS,
                                house_style=[RULE])
    got = enqueued[0]["proposals"]
    assert len(got) == 2
    assert all(p["house_style"] == [RULE] for p in got), (
        "the chip would depend on which proposal the card happens to read first")
    # The originals are not mutated — the caller's list is reused elsewhere in the same pass.
    assert "house_style" not in PROPOSALS[0]


def test_the_rest_of_the_proposal_is_untouched(enqueued):
    handlers._enqueue_proposals("s1", "f.docx", "2.4.4", "Link Purpose", PROPOSALS,
                                house_style=[RULE])
    got = enqueued[0]["proposals"][0]
    assert got["locator"] == "l1" and got["before"] == "click here"
    assert got["proposed_value"] == "Read the policy"


# ── the negative case: no guidance, no chip ──────────────────────────────────────

def test_a_caller_that_passes_nothing_stamps_nothing(enqueued):
    """The default is the safety property. Every deterministic proposer reaches this function
    without a house_style argument, and must come out the other side with no claim attached."""
    handlers._enqueue_proposals("s1", "f.docx", "1.3.2", "Meaningful Sequence", PROPOSALS)
    assert all("house_style" not in p for p in enqueued[0]["proposals"])


@pytest.mark.parametrize("empty", [None, [], ()])
def test_an_empty_house_style_stamps_nothing(enqueued, empty):
    """`memory.applied_rules` returns [] when the flag is off, the org has no rules, or the
    lookup failed — the same conditions under which `guidance_for` returns "". An empty list must
    therefore leave the proposal bare, not carry `house_style: []`, which a careless frontend
    could render as a chip with nothing in it."""
    handlers._enqueue_proposals("s1", "f.docx", "2.4.4", "Link Purpose", PROPOSALS,
                                house_style=empty)
    assert all("house_style" not in p for p in enqueued[0]["proposals"])


def test_the_deterministic_criteria_have_no_house_style_call_site():
    """The load-bearing check, asserted against the source because it is a property of the CALL
    SITES rather than of any one function's behaviour. A future edit that "helpfully" stamps at
    the choke point, or adds house_style= to a deterministic proposer, has to change this."""
    src = (Path(__file__).resolve().parent.parent / "api" / "handlers.py").read_text()
    body = src[src.index("def _propose_text_findings"):src.index("def _enqueue_proposals")]

    # Every criterion enqueued from the scan-time proposal pass, and whether ADR 0021 permits a
    # chip on it — i.e. whether its proposer is handed `guidance=`.
    steered = {"1.3.3", "2.4.4", "2.4.6", "2.4.10"}
    deterministic = {"1.3.2", "1.4.1", "1.4.2", "1.4.8", "1.4.11", "3.1.2", "3.1.5"}
    # 1.1.1 is in NEITHER set, and that is the point of it. Its card is built from two proposers
    # at once: chart datasheets, which are grounded in the sheet's own cells and see no prompt,
    # and per-image vision drafts, which are model-written and now carry `guidance=_g("1.1.1")`.
    # So the criterion is steered and deterministic at the same time, and the honest stamp is
    # per-proposal rather than per-criterion — see test_the_mixed_criterion_stamps_only_its_
    # drafted_half below, which asserts the half that must NOT get a chip still does not.

    for sc in steered:
        assert f'_g("{sc}")' in body, (
            f"{sc} no longer receives guidance, so its house_style stamp now claims an "
            f"influence that did not happen — drop the stamp with the guidance")
    for sc in deterministic:
        assert f'_hs("{sc}")' not in body, (
            f"{sc} is a deterministic proposer and was given a house_style stamp. ADR 0021: "
            f"'Deterministic proposers … ignore memory — there is nothing to steer.' A chip "
            f"here asserts an influence the draft never had")


def test_the_mixed_criterion_stamps_only_its_drafted_half():
    """1.1.1 is the one criterion whose card is assembled from a steered proposer and a
    deterministic one, so it cannot be stamped at the choke point without lying about half of it.

    `_enqueue_proposals(house_style=…)` applies the stamp to EVERY proposal it is handed. The
    1.1.1 enqueue takes `chart_sheets + img_props`; passing the stamp there would put a "house
    style applied" chip on the chart datasheets, whose text is composed from the spreadsheet's
    own adjacent values with no model and no prompt. So the stamp is applied to `img_props`
    alone, at the call site, before the two lists are joined.

    Asserted because it is the kind of thing a later reader tidies up — moving the stamp to the
    enqueue looks like removing a special case, and is how the over-claim gets reintroduced."""
    src = (Path(__file__).resolve().parent.parent / "api" / "handlers.py").read_text()
    body = src[src.index("def _propose_text_findings"):src.index("def _enqueue_proposals")]

    assert '_g("1.1.1")' in body, (
        "the scan-time image drafts no longer receive house-style guidance — 1.1.1 is back to "
        "being the only steered criterion ADR 0021 cannot reach")
    assert '_hs_alt = _hs("1.1.1")' in body and '"house_style": _hs_alt' in body, (
        "the image drafts are no longer stamped with the house style that shaped them")

    enqueue = body[body.index('_enqueue_proposals(scan_id, filename, "1.1.1"'):][:240]
    assert "house_style" not in enqueue, (
        "1.1.1 passes house_style to _enqueue_proposals, which stamps every proposal in the "
        "batch — the deterministic chart datasheets would acquire a chip claiming an influence "
        "they never had")


def test_the_stamp_only_appears_where_guidance_does():
    """The pairing, both directions: every `house_style=_hs(X)` sits with a `guidance=_g(X)`, and
    the count matches. 2.4.9 is the one legitimate exception — its proposals come out of the same
    propose_link_texts call as 2.4.4's, built with _g("2.4.4"), so it carries _hs("2.4.4")."""
    src = (Path(__file__).resolve().parent.parent / "api" / "handlers.py").read_text()
    body = src[src.index("def _propose_text_findings"):src.index("def _enqueue_proposals")]
    import re
    steered = set(re.findall(r'_g\("([\d.]+)"\)', body))
    # Both stamp forms: the keyword at the enqueue for single-proposer criteria, and the
    # per-proposal binding 1.1.1 needs because its batch is mixed (see the test above). Matching
    # only the keyword form would read 1.1.1 as "steered but never reported", which is exactly
    # backwards — it IS reported, on the half that was actually shaped.
    #
    # Both patterns are ANCHORED rather than a bare `_hs("X")` sweep, and that is not fussiness:
    # the comment above the 2.4.4 enqueue names `_hs("2.4.9")` in order to explain why it must
    # NOT be used, so a catch-all reads the warning as the thing it warns against and reports
    # 2.4.9 as stamped-without-guidance.
    stamped = set(re.findall(r'house_style=_hs\("([\d.]+)"\)', body))
    stamped |= set(re.findall(r'_hs_\w+ = _hs\("([\d.]+)"\)', body))
    assert stamped <= steered, (
        f"stamped without guidance: {sorted(stamped - steered)} — each of these would put a "
        f"'house style applied' chip on a draft memory never shaped")
    assert stamped == steered, (
        f"guidance injected but not reported on the card: {sorted(steered - stamped)} — the "
        f"reviewer cannot see what shaped the value they are approving")


# ── it survives the round trip to the SPA ────────────────────────────────────────

def test_the_stamp_survives_the_proposals_json_round_trip(isolated_store):
    """No schema change: the key rides in the existing JSON blob. Driven through the real store
    so a future column-list or serialisation change cannot quietly drop it."""
    stamped = [{**p, "house_style": [RULE]} for p in PROPOSALS]
    isolated_store.enqueue_proposals("s1", "f.docx", "2.4.4", stamped, rule_name="Link Purpose")
    rows = isolated_store.list_hitl_queue(scan_id="s1")
    assert len(rows) == 1
    back = rows[0]["proposals"]
    assert back[0]["house_style"][0]["guidance"] == "Keep link text verb-first."
    assert back[1]["house_style"][0]["rule_id"] == "2.4.4"
