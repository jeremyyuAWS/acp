"""An incrementally-reused analysis is re-scored under THIS RUN's FROZEN scope (ADR 0011 + 3a).

THE BUG. `find_prior_analysis` reuses a file's analysis across scans, gated on owner +
drive_file_id + checksum + rubric_hash. `score`, `compliant` and `skipped_rules` are all
scope-dependent — `_scoped_for_scoring` decides which findings `Rubric.assess` ever sees — and
nothing gated on scope. So: scan wide, narrow the scope, re-scan. The bytes are unchanged and the
rubric is unchanged, so the reuse fires and hands back the score computed under the WIDE scope.
Measured on one .docx with a 1.1.1 and a 1.3.1 finding: 60 unscoped, 75 with only 1.1.1 in scope.

PHASE 3a. ADR 0011 originally re-scored the reuse under the LIVE global scope. 3a reinterprets
"the scope in force now" as THIS run's FROZEN scope: the handler resolves
`store.get_scan_scope(scan_id)` and threads it into `rescore_reused(..., scope=...)`, so the reused
score follows the scope the run was STARTED under — the same scope its traces are gated by — rather
than drifting with a global that may have moved since. This suite pins that the score follows the
scope PASSED IN, and that the handler passes the frozen scope.

WHY RE-SCORE RATHER THAN INVALIDATE. The full issue list comes back WITH the reuse, and scoring is
a pure function over it — so the score can be recomputed for free while the download, the engine and
the OCR all stay skipped. That is what `_scoped_for_scoring` already promises: "Every finding stays
on the record, so re-reporting the same scan under a different scope needs no re-scan."
"""
import sys
from pathlib import Path

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
NARROW = {"1.1.1": frozenset({"docx"})}   # a FROZEN per-run scope, passed straight to rescore_reused


def test_the_score_really_does_depend_on_the_scope():
    """The premise. If these two were equal the rest of this file would prove nothing."""
    wide = scanner.rescore_reused(ISSUES, "a.docx", scope=None)
    narrow = scanner.rescore_reused(ISSUES, "a.docx", scope=NARROW)
    assert wide["score"] != narrow["score"], (
        f"both scopes scored {wide['score']} — this corpus cannot detect the bug")
    assert narrow["score"] > wide["score"], "dropping a finding from scope should raise the score"


def test_a_reused_analysis_is_scored_under_this_runs_frozen_scope():
    """The fix. The same stored findings, re-scored under the FROZEN scope handed in, must match a
    fresh score computed under that same frozen scope — deterministic per run, not per global."""
    out = scanner.rescore_reused(ISSUES, "a.docx", scope=NARROW)
    fresh = scanner.rescore_reused(ISSUES, "a.docx", scope=NARROW)
    assert out["score"] == fresh["score"], "a reused file must score as a freshly-scanned one"


def test_the_frozen_scope_passed_in_governs_not_any_live_global(monkeypatch):
    """The scope is the one THREADED IN. rescore_reused reads no global at all now — set the live
    override the opposite way and the score must still follow the frozen argument."""
    # A live global that would keep BOTH findings (no restriction) — the pre-3a source of drift.
    monkeypatch.setattr(pol, "_scope_override", "", raising=False)
    narrow = scanner.rescore_reused(ISSUES, "a.docx", scope=NARROW)
    wide = scanner.rescore_reused(ISSUES, "a.docx", scope=None)
    assert narrow["score"] > wide["score"], (
        "the frozen scope argument must govern the reused score, independent of the live global")


def test_it_returns_only_the_score_keys():
    """`issues`, `engine`, `acp_stamped` and everything else reused must pass through untouched —
    this overwrites a scored fdict, it does not rebuild one."""
    out = scanner.rescore_reused(ISSUES, "a.docx", scope=None)
    assert set(out) <= {"score", "compliant", "skipped_rules"}
    assert "issues" not in out and "engine" not in out


def test_an_errored_file_is_not_scored_as_a_successful_one():
    """`status` carries through to Rubric.assess's `succeeded` flag. A file that failed to
    analyse must not be re-scored as though its (empty) finding list meant conformance."""
    ok = scanner.rescore_reused([], "a.docx", "analysed", scope=None)
    bad = scanner.rescore_reused([], "a.docx", "error", scope=None)
    assert ok != bad, "an errored reuse must not score identically to a clean one"


def test_the_handler_rescores_under_the_frozen_scope_rather_than_trusting_the_stored_score():
    """The wiring, asserted on the source.

    A unit test of `rescore_reused` passes whether or not anything calls it, and "the helper
    exists but nothing invokes it" is the exact shape of a fix that looks done. Checked here
    rather than by driving the whole fan-out, which needs a Store, a Drive double and a job row.
    """
    src = (ROOT / "api" / "handlers.py").read_text()
    # The reuse branch, from `if dedup:` to the `except` that closes its rescore try/except. Anchored
    # on that `except` rather than a fixed +N char window: the window has to reach past the call, the
    # fdict.update and the get_scan_scope arg, and a fixed offset silently clips whichever lands last
    # the moment a comment is added above the call (which is exactly how it broke once).
    _start = src.index("if dedup:")
    block = src[_start:src.index("except Exception", _start)]
    # The INVOCATION, not the name. Asserting `"rescore_reused" in block` passes on the import
    # line alone — verified by deleting the call and watching this test stay green, which is the
    # "a check that cannot fail is indistinguishable from a check that passed" shape. The result
    # must also be written back onto fdict, or the score is recomputed and thrown away.
    assert "rescore_reused(" in block, (
        "the incremental reuse path must CALL rescore_reused; without it the stored score, "
        "computed under whatever scope was active last time, is copied forward")
    assert "fdict.update(" in block, (
        "the recomputed score must overwrite the reused one, not be discarded")
    # PHASE 3a — it must pass the scan's FROZEN scope, not the live global. Without this the reuse
    # would drift with a global setting that moved after the scan started.
    assert "get_scan_scope(scan_id)" in block, (
        "the reuse re-score must be threaded THIS scan's frozen scope (get_scan_scope), "
        "not the live global — otherwise an old scan's reused score moves when the global does")
