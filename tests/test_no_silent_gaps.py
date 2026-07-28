"""ADR 0026 Epic 1 — the no-silent-gaps contract: every catalogued criterion × format × signal
combination resolves to an EXPLICIT outcome. A criterion may be PASS, FAIL, REVIEW, or
NOT_EVALUATED — it may never fall through to None, raise, or invent a new token. This is the
test that keeps 'evaluated + not_evaluated + review == catalog_size' true forever."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))
import store as store_mod  # noqa: E402

FORMATS = ("docx", "xlsx", "pptx", "pdf", "html", None)   # None = unknown format
SIGNALS = ((0, 0), (1, 0), (0, 1), (2, 3))                # (fail_count, review_count)
ALLOWED = {"PASS", "FAIL", store_mod.REVIEW, store_mod.NOT_EVALUATED,
           getattr(store_mod, "_LEGACY_NOT_EVALUATED", store_mod.NOT_EVALUATED)}


def test_every_criterion_format_signal_resolves_explicitly():
    unresolved = []
    for rule in store_mod.RULE_CATALOG:
        for fmt in FORMATS:
            for fails, reviews in SIGNALS:
                try:
                    out = store_mod._rule_outcome(rule["id"], fmt, fails, reviews)
                except Exception as e:   # a raise IS a silent gap — the scan would misreport
                    unresolved.append((rule["id"], fmt, fails, reviews, f"raised {e!r}"))
                    continue
                if out not in ALLOWED:
                    unresolved.append((rule["id"], fmt, fails, reviews, f"got {out!r}"))
    assert not unresolved, f"criteria without an explicit outcome: {unresolved[:10]}"


def test_a_blocking_finding_is_never_swallowed():
    """Whatever the lane, fail_count > 0 must surface as FAIL — a fail can never be silently
    reclassified into a softer outcome by LANE bookkeeping.

    Scoped to criteria at or below the conformance target. A criterion above the target was
    never in scope for the scan, so it has no outcome to swallow — see the companion test
    below, which pins that exception down rather than leaving it as a hole in this one.
    """
    for rule in store_mod.RULE_CATALOG:
        if not store_mod.in_target(rule["id"], store_mod.DEFAULT_TARGET):
            continue
        for fmt in ("docx", "xlsx", "pptx", "pdf", "html"):
            assert store_mod._rule_outcome(rule["id"], fmt, 1, 0) == "FAIL", (rule["id"], fmt)


def test_a_criterion_above_the_target_is_not_assessed_at_all():
    """The one deliberate exception to the rule above, and the reason it is safe.

    Several detectors compute the AA and AAA thresholds in a single pass — the contrast checks
    emit both — so an AAA finding can exist on a scan whose target is AA. Reporting it would
    fail a document against a bar nobody asked it to meet.

    The finding is not "swallowed": it was never in scope. `filter_issues_to_target` drops such
    findings before counts are computed, and this gate is the backstop for callers passing raw
    counts. Both A and AA targets exclude AAA, because AAA is not a selectable target.
    """
    aaa = [r["id"] for r in store_mod.RULE_CATALOG if (r.get("level") or "A") == "AAA"]
    assert aaa, "expected AAA criteria in the catalog"
    for rid in aaa:
        for target in store_mod.TARGET_LEVELS:
            assert store_mod._rule_outcome(rid, "docx", 1, 0, target) == store_mod.NOT_EVALUATED

    # An AA criterion is out of scope at target A, and in scope at AA — the levels nest.
    assert store_mod._rule_outcome("1.4.3", "docx", 1, 0, "A") == store_mod.NOT_EVALUATED
    assert store_mod._rule_outcome("1.4.3", "docx", 1, 0, "AA") == "FAIL"
    # A level-A criterion is in scope at every selectable target.
    for target in store_mod.TARGET_LEVELS:
        assert store_mod._rule_outcome("1.1.1", "docx", 1, 0, target) == "FAIL"


def test_findings_above_the_target_are_filtered_before_counting():
    """The upstream half: an AAA finding never reaches the counts that drive an outcome."""
    issues = [
        {"ruleId": "X_LOW_CONTRAST", "wcag": "1.4.3 Contrast (Minimum)", "severity": "SERIOUS"},
        {"ruleId": "X_LOW_CONTRAST_AAA", "wcag": "1.4.6 Contrast (Enhanced)", "severity": "MODERATE"},
    ]
    kept = store_mod.filter_issues_to_target(issues, "AA")
    assert [i["ruleId"] for i in kept] == ["X_LOW_CONTRAST"]
    assert store_mod.filter_issues_to_target(issues, "A") == []
    # A finding whose wcag string carries no SC is kept — dropping it would hide a real problem
    # on the strength of a formatting quirk.
    odd = [{"ruleId": "X", "wcag": "", "severity": "SERIOUS"}]
    assert store_mod.filter_issues_to_target(odd, "A") == odd
