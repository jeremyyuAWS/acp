"""corpus_expectations must agree with the real `_rule_outcome`, pair by pair.

The module is a SECOND expression of `_rule_outcome`'s branch logic, written for callers who have
no finding counts yet — a corpus author deciding what a fixture should expect. Two expressions of
one rule is a drift hazard, and the only thing that makes it acceptable is this file: it drives
the real function with synthetic counts across every scopeable pair and asserts the derived answer
matches. If someone changes a lane, a coverage tier or the certify gate, the copy fails here
rather than quietly telling corpus authors the wrong thing.

The failure this whole line of work exists to prevent: a manifest marking a clean 2.1.2 docx
fixture `pass`. 2.1.2 is a review lane, which "resolves to REVIEW when its detector fires and to
NOT_EVALUATED when it does not — it NEVER resolves to PASS". That expectation can never be met,
so it reports a false failure on every run, forever, and it looks like an ACP bug.
"""
from __future__ import annotations

import sys
from pathlib import Path

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))
sys.path.insert(0, str(ACP / "scripts"))

import assessment_policy as pol          # noqa: E402
import corpus_expectations as ce         # noqa: E402

PAIRS = [(sc, f) for sc, fmts in pol.SCOPE_PRESETS["acp-core-17"].items() for f in sorted(fmts)]


def test_there_are_pairs_to_check():
    assert len(PAIRS) == 62


def test_clean_verdict_matches_the_engine_on_a_clean_scan():
    """Zero findings through the REAL _rule_outcome, for all 62 pairs."""
    for sc, fmt in PAIRS:
        want = pol._rule_outcome(sc, fmt, 0, 0)
        got = ce.clean_verdict(sc, fmt)
        assert got == want, f"{sc} x {fmt}: derived {got}, _rule_outcome says {want}"


def test_a_blocking_finding_is_always_FAIL():
    """The hoist in _rule_outcome: a recorded blocking finding is a fact and outranks the format
    bookkeeping, so FAIL is reachable for every in-scope, in-target pair."""
    for sc, fmt in PAIRS:
        assert pol._rule_outcome(sc, fmt, 1, 0) == "FAIL", f"{sc} x {fmt}"
        assert "FAIL" in ce.possible_verdicts(sc, fmt)


def test_every_engine_answer_is_inside_possible_verdicts():
    """Drive the real function across the finding-count space and assert nothing escapes the set
    a manifest is allowed to expect. A verdict outside it would mean a corpus author is told an
    expectation is unreachable when ACP can in fact produce it."""
    for sc, fmt in PAIRS:
        allowed = ce.possible_verdicts(sc, fmt)
        for fails, reviews in ((0, 0), (0, 1), (1, 0), (1, 1), (3, 2)):
            got = pol._rule_outcome(sc, fmt, fails, reviews)
            assert got in allowed, (
                f"{sc} x {fmt} with fail={fails} review={reviews}: engine says {got}, "
                f"possible_verdicts offers only {sorted(allowed)}")


def test_review_lane_pairs_can_never_pass():
    """The specific trap. Asserted against the ENGINE, not just the derivation."""
    lanes = [(sc, f) for sc, fmts in pol.REVIEW_FORMATS.items() for f in sorted(fmts)]
    assert lanes, "REVIEW_FORMATS is empty — this test would prove nothing"
    for sc, fmt in lanes:
        for fails, reviews in ((0, 0), (0, 1), (0, 5)):
            assert pol._rule_outcome(sc, fmt, fails, reviews) != "PASS", f"{sc} x {fmt}"
        assert not ce.can_ever_pass(sc, fmt), f"{sc} x {fmt} claims it can PASS"


def test_a_clean_review_lane_is_not_evaluated_not_pass():
    """2.1.2 x docx by name, because it is the example a corpus author is most likely to get
    wrong: nothing fired, so nothing was reviewed, so nobody looked."""
    assert ce.clean_verdict("2.1.2", "docx") == ce.NOT_EVALUATED
    assert pol._rule_outcome("2.1.2", "docx", 0, 0) == ce.NOT_EVALUATED


def test_most_of_the_core_17_cannot_certify_a_pass():
    """A number worth pinning, because it is the whole argument for this module. If a future
    change makes most pairs certifiable this test should fail and be re-read — the point is that
    nobody discovers the ratio by accident while writing a manifest."""
    cannot = [p for p in PAIRS if not ce.can_ever_pass(*p)]
    assert len(cannot) > len(PAIRS) // 2, (
        "fewer than half the pairs are non-certifying now — good news, but the corpus guidance "
        "and this test's premise both need re-reading")


def test_validate_rejects_an_unreachable_expectation():
    problems = ce.validate([
        {"file": "clean.docx", "sc": "2.1.2", "format": "docx", "expected": "pass"},
    ])
    assert len(problems) == 1
    assert "can never PASS" in problems[0]
    assert "review lane" in problems[0]


def test_validate_accepts_a_reachable_one():
    assert ce.validate([
        {"file": "clean.docx", "sc": "2.1.2", "format": "docx", "expected": "not_evaluated"},
        {"file": "broken.docx", "sc": "2.1.2", "format": "docx", "expected": "fail"},
        {"file": "lang.docx", "sc": "3.1.1", "format": "docx", "expected": "pass"},
    ]) == []


def test_not_applicable_is_refused_by_name():
    """The PRD's manifest schema used `not_applicable`. assessment_policy renamed that away
    because it "asserts the criterion is out of scope; the truth is only that we didn't look" —
    accepting the word here would reintroduce the claim through the corpus."""
    problems = ce.validate([
        {"file": "x.docx", "sc": "2.1.2", "format": "docx", "expected": "not_applicable"},
    ])
    assert len(problems) == 1
    assert "not_applicable" in problems[0]
