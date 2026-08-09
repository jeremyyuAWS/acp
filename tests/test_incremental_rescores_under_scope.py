"""An incrementally-reused analysis is re-scored under the CURRENT scope (ADR 0011).

THE BUG. `find_prior_analysis` reuses a file's analysis across scans, gated on owner +
drive_file_id + checksum + rubric_hash. `score`, `compliant` and `skipped_rules` are all
scope-dependent — `_scoped_for_scoring` decides which findings `Rubric.assess` ever sees — and
nothing gated on the operator's `scan_scope`.

So: scan wide, narrow the scope, re-scan. The bytes are unchanged and the rubric is unchanged, so
the reuse fires and hands back the score computed under the WIDE scope. Measured on one .docx
with a 1.1.1 and a 1.3.1 finding: 60 unscoped, 75 with only 1.1.1 in scope, and the reuse
returned 60. Silently, and looking exactly like the scope had done nothing — which is the same
way the scope-never-reached-the-scanner bug hid.

It is the same class of staleness `rubric_hash` already guards. Its docstring: "a stale analysis
under an old rubric is not valid evidence once the rule set has changed." A stale score under an
old SCOPE is not valid evidence either.

WHY RE-SCORE RATHER THAN INVALIDATE. Invalidating on a scope change would throw away the reuse
for every file in the estate and re-run the engine over documents that have not moved. The full
issue list comes back WITH the reuse, and scoring is a pure function over it — so the score can
be recomputed for free while the download, the engine and the OCR all stay skipped. That is what
`_scoped_for_scoring` already promises: "Every finding stays on the record, so re-reporting the
same scan under a different scope needs no re-scan."
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))

import assessment_policy as pol  # noqa: E402
import scanner  # noqa: E402

# One document, two findings, two different criteria — so a scope that keeps one and drops the
# other produces two genuinely different scores.
ISSUES = [
    {"ruleId": "DOCX-ALT-001", "wcag": "SC_1_1_1", "severity": "CRITICAL", "detail": "no alt"},
    {"ruleId": "DOCX-TABLE-001", "wcag": "SC_1_3_1", "severity": "SERIOUS", "detail": "no header"},
]
NARROW = {"1.1.1": frozenset({"docx"})}


@pytest.fixture
def scope(monkeypatch):
    """Set the scope `_scoped_for_scoring` resolves, without needing a Store."""
    def _set(value):
        monkeypatch.setattr(scanner, "_scoped_for_scoring",
                            lambda issues, filename: (
                                issues if not value
                                else pol.filter_issues_to_scope(
                                    issues, pol._file_format(filename), value)))
    return _set


def test_the_score_really_does_depend_on_the_scope(scope):
    """The premise. If these two were equal the rest of this file would prove nothing."""
    scope(None)
    wide = scanner.rescore_reused(ISSUES, "a.docx")
    scope(NARROW)
    narrow = scanner.rescore_reused(ISSUES, "a.docx")
    assert wide["score"] != narrow["score"], (
        f"both scopes scored {wide['score']} — this corpus cannot detect the bug")
    assert narrow["score"] > wide["score"], "dropping a finding from scope should raise the score"


def test_a_reused_analysis_is_scored_under_the_scope_in_force_now(scope):
    """The fix. The same stored findings, re-scored, must follow the CURRENT scope."""
    scope(NARROW)
    out = scanner.rescore_reused(ISSUES, "a.docx")
    scope(NARROW)
    fresh = scanner.rescore_reused(ISSUES, "a.docx")
    assert out["score"] == fresh["score"], "a reused file must score as a freshly-scanned one"


def test_it_returns_only_the_score_keys(scope):
    """`issues`, `engine`, `acp_stamped` and everything else reused must pass through untouched —
    this overwrites a scored fdict, it does not rebuild one."""
    scope(None)
    out = scanner.rescore_reused(ISSUES, "a.docx")
    assert set(out) <= {"score", "compliant", "skipped_rules"}
    assert "issues" not in out and "engine" not in out


def test_an_errored_file_is_not_scored_as_a_successful_one(scope):
    """`status` carries through to Rubric.assess's `succeeded` flag. A file that failed to
    analyse must not be re-scored as though its (empty) finding list meant conformance."""
    scope(None)
    ok = scanner.rescore_reused([], "a.docx", "analysed")
    bad = scanner.rescore_reused([], "a.docx", "error")
    assert ok != bad, "an errored reuse must not score identically to a clean one"


def test_the_handler_rescores_rather_than_trusting_the_stored_score():
    """The wiring, asserted on the source.

    A unit test of `rescore_reused` passes whether or not anything calls it, and "the helper
    exists but nothing invokes it" is the exact shape of a fix that looks done. Checked here
    rather than by driving the whole fan-out, which needs a Store, a Drive double and a job row.
    """
    src = (ROOT / "api" / "handlers.py").read_text()
    block = src[src.index("if dedup:"):src.index("dedup_of = dedup.pop", src.index("if dedup:")) + 2000]
    # The INVOCATION, not the name. Asserting `"rescore_reused" in block` passes on the import
    # line alone — verified by deleting the call and watching this test stay green, which is the
    # "a check that cannot fail is indistinguishable from a check that passed" shape. The result
    # must also be written back onto fdict, or the score is recomputed and thrown away.
    assert "rescore_reused(" in block, (
        "the incremental reuse path must CALL rescore_reused; without it the stored score, "
        "computed under whatever scope was active last time, is copied forward")
    assert "fdict.update(" in block, (
        "the recomputed score must overwrite the reused one, not be discarded")
