"""`in` — set membership, and the roster rule that could not be written without it.

WHAT WAS MISSING, and why it did not look missing. Conditions in a match are ANDed and there is
no OR, so "archive files owned by anyone on this list of 200 departed staff, older than five
years" was not one rule. It was **200 policies**, each with its own approval and its own audit
trail. `docs/sharepoint-gaps.md` recorded the gap as an input the customer owed — *"'departed'
needs the UTSW roster as an input (the SOW puts rule-supply on UTSW)"* — which reads as though
there were somewhere to put a roster once they handed one over. There was not. Same shape as the
folder-rule row before #1358: a missing mechanism described as a missing input.

THE TWO DESIGN CALLS, both pinned below because both are the kind that fail silently:

  1. **Case-insensitive**, diverging from `eq`. Every value this operator is written against is
     an identity supplied from elsewhere — a roster export, an HR extract, a column copied out of
     SharePoint — and "Alice@utsw.edu" missing "alice@utsw.edu" is a silent miss on exactly the
     documents the rule exists to catch. The engine is already mixed (`contains`/`prefix` fold,
     `eq`/`ne` do not), so this joins the folding half. It is a real trap and it is stated rather
     than left to be discovered.
  2. **A list-valued observation intersects.** A SharePoint multi-choice managed column arrives
     as a list; asking "is this whole list one of the allowed values" answers False for every one
     of them.

And the value shape is validated at SAVE time, not match time: a string or an empty list would
match nothing, and both would otherwise validate, save, and sit in the policy list looking like a
working roster rule forever.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

import disposition  # noqa: E402

ROSTER = ["alice@utsw.edu", "Bob@UTSW.edu", "carol@utsw.edu"]
OWNED_BY_LEAVER = [{"field": "owner", "op": "in", "value": ROSTER}]


# ── the rule the gap row is about ────────────────────────────────────────────────────────────

def test_one_rule_covers_the_whole_roster():
    for who in ("alice@utsw.edu", "bob@utsw.edu", "carol@utsw.edu"):
        assert disposition.matches({"owner": who}, OWNED_BY_LEAVER) is True


def test_somebody_not_on_it_is_not_matched():
    assert disposition.matches({"owner": "dave@utsw.edu"}, OWNED_BY_LEAVER) is False


def test_the_full_departed_employee_rule_reads_as_one_condition_set():
    """What 200 policies used to be. The AND with an age condition is the whole point — a roster
    rule that archived a leaver's files regardless of age would take last week's work with it."""
    rule = OWNED_BY_LEAVER + [{"field": "modified_age_days", "op": "gt", "value": 1825}]
    old = {"owner": "alice@utsw.edu", "source_modified": "2015-01-01T00:00:00+00:00"}
    recent = {"owner": "alice@utsw.edu", "source_modified": "2026-08-01T00:00:00+00:00"}
    assert disposition.matches(old, rule) is True
    assert disposition.matches(recent, rule) is False


# ── case folding, and its divergence from eq ─────────────────────────────────────────────────

def test_case_does_not_decide_whether_a_leavers_files_are_found():
    """The silent-miss case. A roster exported from one system and owners recorded by another
    will not agree on casing, and the miss is invisible: the rule runs, matches fewer files, and
    nothing says why."""
    assert disposition.matches({"owner": "ALICE@UTSW.EDU"}, OWNED_BY_LEAVER) is True
    assert disposition.matches({"owner": "bob@utsw.edu"}, OWNED_BY_LEAVER) is True


def test_this_DIVERGES_from_eq_and_that_is_deliberate():
    """Pinned so the inconsistency is a decision on the record rather than a surprise. `eq` is
    exact; `in` folds, like `contains` and `prefix` already do."""
    assert disposition.matches({"owner": "ALICE@UTSW.EDU"},
                               [{"field": "owner", "op": "eq", "value": "alice@utsw.edu"}]) is False
    assert disposition.matches({"owner": "ALICE@UTSW.EDU"},
                               [{"field": "owner", "op": "in", "value": ["alice@utsw.edu"]}]) is True


# ── shapes the observed value actually arrives in ────────────────────────────────────────────

def test_a_multi_value_column_intersects_rather_than_failing():
    """A SharePoint multi-choice managed column arrives as a list. Asking "is this list one of
    the allowed values" answers False for every one of them — a silent miss one field over."""
    rule = [{"field": "managed:Records Category", "op": "in", "value": ["Active", "Superseded"]}]
    doc = {"managed_columns": {"Records Category": ["Draft", "Superseded"]}}
    assert disposition.matches(doc, rule) is True
    assert disposition.matches({"managed_columns": {"Records Category": ["Draft"]}}, rule) is False


def test_numbers_compare_as_numbers_and_a_string_is_not_a_number():
    """Folding is for STRINGS only, so `in` types-match the way `eq` does (`"20" == 20` is False)
    rather than stringifying both sides.

    The second assertion is the one with teeth, and the first version of this test did not have
    it: `str(20).casefold() == str(20).casefold()`, so a coerce-everything implementation passes
    a test that only checks 20 against [10, 20]. It takes a document whose value is the STRING
    "20" to tell the two apart — and the engine's own precedent is that the difference is real
    (`draftToMatch` coerces days to a number precisely because `'1095' > 999` is not what it
    looks like)."""
    rule = [{"field": "size_kb", "op": "in", "value": [10, 20]}]
    assert disposition.matches({"size_kb": 20}, rule) is True
    assert disposition.matches({"size_kb": 15}, rule) is False
    assert disposition.matches({"size_kb": "20"}, rule) is False, (
        "a string was compared to a number by stringifying both sides — `eq` would not")


def test_an_absent_value_is_not_a_member_of_anything():
    """Not an error, and not a match. A document with no owner is not owned by a leaver."""
    assert disposition.matches({"owner": None}, OWNED_BY_LEAVER) is False
    assert disposition.matches({}, OWNED_BY_LEAVER) is False


def test_a_roster_of_one_still_works():
    assert disposition.matches({"owner": "alice@utsw.edu"},
                               [{"field": "owner", "op": "in", "value": ["alice@utsw.edu"]}])


# ── the value shape is refused at SAVE time ──────────────────────────────────────────────────

def test_a_string_value_is_refused_rather_than_silently_matching_nothing():
    """The trap this check exists for: `{"op": "in", "value": "alice@utsw.edu"}` is what somebody
    writes first. It is not a list, so it matches nothing — and without this it would validate,
    save, and look like a working roster rule forever."""
    with pytest.raises(ValueError, match="non-empty list"):
        disposition.validate_match([{"field": "owner", "op": "in", "value": "alice@utsw.edu"}])


def test_an_empty_list_is_refused():
    """A rule that can never fire, saved beside rules that can. Same judgement as
    validate_action_config refusing a tag policy with no tags."""
    with pytest.raises(ValueError, match="never match"):
        disposition.validate_match([{"field": "owner", "op": "in", "value": []}])


def test_the_refusal_points_at_eq_for_the_single_value_case():
    with pytest.raises(ValueError, match="a single value is 'eq'"):
        disposition.validate_match([{"field": "owner", "op": "in", "value": "x"}])


def test_a_well_formed_roster_rule_validates():
    disposition.validate_match(OWNED_BY_LEAVER)


def test_the_operator_is_offered_in_the_unknown_op_error():
    """The error names the allowed set, so `in` has to be discoverable there — that message is
    how an API caller finds out what exists."""
    with pytest.raises(ValueError, match="'in'"):
        disposition.validate_match([{"field": "owner", "op": "nope", "value": "x"}])


# ── the audit evidence a records manager reads ───────────────────────────────────────────────

def _reason(doc):
    return disposition.evaluate(doc, OWNED_BY_LEAVER)["conditions"][0]["reason"]


def test_a_match_says_which_list_it_matched():
    """The disposition audit trail is what a records manager defends. Falling through to the
    generic "condition satisfied" would say a rule fired and not why — for the one rule whose
    justification IS the list."""
    assert "is one of" in _reason({"owner": "alice@utsw.edu"})
    assert "condition satisfied" != _reason({"owner": "alice@utsw.edu"})


def test_a_miss_says_so_too():
    assert "is not one of" in _reason({"owner": "dave@utsw.edu"})


def test_an_absent_field_is_distinguished_from_a_value_not_on_the_list():
    """"We could not read the owner" and "the owner is not a leaver" are different facts about
    whether this document should be archived, and the evidence must not collapse them."""
    ev = disposition.evaluate({"owner": None, "sp_availability": {"owner": "unavailable"}},
                              OWNED_BY_LEAVER)
    assert "not one of" in ev["conditions"][0]["reason"]
