"""The operator scope gate, end to end: the setting must be READ, and it must gate SCORES too.

`SCOPE_PRESETS` landed in #76 with `active_scope()` / `in_scope()` and a `scan_scope` setting, and
until this suite nothing exercised any of it. Two independent defects were hiding in that gap, and
both had the same signature — a feature flag that is off in a way nothing can distinguish from a
feature flag that works:

1. THE SETTING WAS NEVER READ. `_rule_outcome` called `in_scope(rule_id, fmt)` with no scope, and
   `in_scope` resolves a missing scope through `active_scope()` with no Store — which can only see
   the `_scope_override` module global, a value nothing in the codebase assigns. So writing
   `scan_scope` to the settings table gated NOTHING, silently. Verified before the fix:

       store.get_setting("scan_scope")        -> 'engagement-14'
       active_scope(store)                    -> the 14-criterion map
       active_scope()      (as in_scope calls it) -> None   == no restriction
       _rule_outcome('4.1.2', 'docx', fail=3) -> 'FAIL'     == gate never fired

2. SCORES IGNORED THE SCOPE. `Rubric.assess` computes `100 - sum(penalty(severity))` over every
   finding handed to it and knows nothing about scope, while `_rule_outcome` gated the per-criterion
   traces. A scoped scan therefore produced scoped TRACES and unscoped SCORES — a document showing
   no in-scope findings beside a score penalised for findings the UI had correctly stopped
   displaying. That is the contradiction the scope exists to prevent, one layer down.

The safety property is asserted too, because it is what makes this deployable: with no scope set
the gate is the identity function, so an unscoped deployment scores exactly as it did before.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))

import assessment_policy as ap          # noqa: E402
from rubric import Rubric               # noqa: E402

ENGAGEMENT = "engagement-14"
# 4.1.2 is in scope for pdf ONLY, so the same criterion answers differently per format — which is
# what makes it the useful probe: a format-blind bug passes a criterion-only assertion.
PDF_ONLY = "4.1.2"
# 1.4.11 is a document-core criterion the engagement left OUT entirely, on every format.
OUT_OF_SCOPE = "1.4.11"
IN_SCOPE_ALL = "1.1.1"


@pytest.fixture
def scoped():
    """The 14-criterion preset resolved as a scope map, without touching module globals."""
    return ap.SCOPE_PRESETS[ENGAGEMENT]


@pytest.fixture
def store(tmp_path, monkeypatch):
    """A real Store on a throwaway SQLite file."""
    import store as store_mod
    monkeypatch.setattr(store_mod, "_SQLITE_PATH", str(tmp_path / "t.db"), raising=False)
    return store_mod.Store()


# ── Defect 1: the setting has to be readable ──────────────────────────────────────────

def test_setting_written_to_the_store_is_what_active_scope_returns(store):
    store.set_setting(ap.SCOPE_SETTING, ENGAGEMENT)
    scope = ap.active_scope(store)
    assert scope is not None, "the scan_scope setting did not resolve to a scope"
    assert len(scope) == 14


def test_absent_setting_means_no_restriction(store):
    assert ap.active_scope(store) is None
    assert store.get_setting(ap.SCOPE_SETTING, "") in ("", None)


def test_empty_setting_means_no_restriction(store):
    """"" is the documented "explicitly unscoped" value and must not resolve to a preset."""
    store.set_setting(ap.SCOPE_SETTING, "")
    assert ap.active_scope(store) is None


def test_unknown_preset_name_does_not_invent_a_scope(store):
    """A typo must fail OPEN (assess everything), never silently narrow the assertion."""
    store.set_setting(ap.SCOPE_SETTING, "engagement-typo")
    assert ap.active_scope(store) is None


def test_rule_outcome_honours_a_scope_passed_in(scoped):
    """The regression test for defect 1: the gate fires when the caller threads the scope."""
    assert ap._rule_outcome(PDF_ONLY, "docx", 3, 0, "AA", scoped) == ap.NOT_EVALUATED
    assert ap._rule_outcome(PDF_ONLY, "pdf", 3, 0, "AA", scoped) == "FAIL"
    assert ap._rule_outcome(OUT_OF_SCOPE, "pdf", 3, 0, "AA", scoped) == ap.NOT_EVALUATED
    assert ap._rule_outcome(IN_SCOPE_ALL, "docx", 3, 0, "AA", scoped) == "FAIL"


def test_a_recorded_finding_does_not_resurrect_an_out_of_scope_pair(scoped):
    """"A recorded finding is a FACT" is deliberately outranked by the scope gate, like target."""
    for fmt in ("docx", "xlsx", "pptx", "pdf"):
        assert ap._rule_outcome(OUT_OF_SCOPE, fmt, 99, 0, "AA", scoped) == ap.NOT_EVALUATED


def test_unparsed_format_is_never_excluded(scoped):
    """The gate honours a deliberate choice; it does not invent one from an unreadable filename."""
    assert ap._rule_outcome(PDF_ONLY, None, 3, 0, "AA", scoped) == "FAIL"
    assert ap.in_scope(PDF_ONLY, None, scoped) is True


# ── Defect 2: scores have to follow the scope ─────────────────────────────────────────

def issue(sc: str, severity: str = "CRITICAL") -> dict:
    return {"ruleId": f"rule-{sc}", "wcag": f"SC_{sc.replace('.', '_')}", "severity": severity}


def rubric() -> Rubric:
    import json
    cfg = ROOT / "config" / "rubric.active.json"
    if not cfg.exists():
        cfg = ROOT / "config" / "rubric.default.json"
    return Rubric(json.loads(cfg.read_text()))


def test_filter_drops_only_the_out_of_scope_pairs(scoped):
    issues = [issue(IN_SCOPE_ALL), issue(OUT_OF_SCOPE), issue(PDF_ONLY)]
    on_pdf = ap.filter_issues_to_scope(issues, "pdf", scoped)
    assert [i["wcag"] for i in on_pdf] == ["SC_1_1_1", "SC_4_1_2"]      # 1.4.11 gone
    on_docx = ap.filter_issues_to_scope(issues, "docx", scoped)
    assert [i["wcag"] for i in on_docx] == ["SC_1_1_1"]                 # 4.1.2 is pdf-only


def test_filter_is_the_identity_with_no_scope():
    """The property that makes this safe to deploy before anyone turns the scope on."""
    issues = [issue(IN_SCOPE_ALL), issue(OUT_OF_SCOPE), issue("3.3.2")]
    for scope in (None, {}):
        assert ap.filter_issues_to_scope(issues, "docx", scope) == issues


def test_a_finding_with_no_recognisable_sc_is_kept(scoped):
    """Better to over-count than to drop a finding nobody can attribute to a criterion."""
    odd = {"ruleId": "x", "wcag": "not-a-criterion", "severity": "SERIOUS"}
    assert ap.filter_issues_to_scope([odd], "pdf", scoped) == [odd]


def test_out_of_scope_findings_no_longer_penalise_the_score(scoped):
    """The core of defect 2, stated as the two scores a customer could be shown."""
    rb = rubric()
    issues = [issue(IN_SCOPE_ALL), issue(OUT_OF_SCOPE), issue(OUT_OF_SCOPE)]

    unscoped = rb.assess(True, issues, [])
    scoped_ = rb.assess(True, ap.filter_issues_to_scope(issues, "pdf", scoped), [])

    assert unscoped["score"] < scoped_["score"], (
        "scoping the score changed nothing — the out-of-scope findings still penalise it")
    # And the scoped score is exactly the in-scope penalty, not an approximation of it.
    only_in_scope = rb.assess(True, [issue(IN_SCOPE_ALL)], [])
    assert scoped_["score"] == only_in_scope["score"]


def test_a_document_failing_only_out_of_scope_criteria_scores_clean(scoped):
    """The case that produced the contradiction: no in-scope findings, yet a penalised score."""
    rb = rubric()
    issues = [issue(OUT_OF_SCOPE), issue("1.4.4"), issue("2.1.2")]
    scoped_ = rb.assess(True, ap.filter_issues_to_scope(issues, "pdf", scoped), [])
    assert scoped_["score"] == 100
    assert scoped_["compliant"] is True
    # …and unscoped it does not, which is what the drawer would have contradicted.
    assert rb.assess(True, issues, [])["score"] < 100


def test_scoping_never_lowers_a_score(scoped):
    """A scope narrows what is assessed, so it can only ever remove penalties."""
    rb = rubric()
    for fmt in ("docx", "xlsx", "pptx", "pdf"):
        for sev in ("CRITICAL", "SERIOUS", "MODERATE", "MINOR"):
            issues = [issue(sc, sev) for sc in (IN_SCOPE_ALL, OUT_OF_SCOPE, PDF_ONLY, "3.3.2")]
            full = rb.assess(True, issues, [])["score"]
            narrowed = rb.assess(True, ap.filter_issues_to_scope(issues, fmt, scoped), [])["score"]
            assert narrowed >= full, f"{fmt}/{sev}: scoping lowered the score"


def test_error_status_stays_unscored_whatever_the_scope(scoped):
    """Track-A safety rule: an unopenable file is never scored, and a scope cannot make it a pass."""
    rb = rubric()
    out = rb.assess(False, ap.filter_issues_to_scope([issue(OUT_OF_SCOPE)], "pdf", scoped), [])
    assert out["score"] is None
    assert out["compliant"] is False


def test_uncertain_stays_uncertain_and_uncertifiable(scoped):
    """A skipped rule means the score is an upper bound; scoping must not certify around it."""
    rb = rubric()
    out = rb.assess(True, ap.filter_issues_to_scope([issue(OUT_OF_SCOPE)], "pdf", scoped),
                    [{"rule": "some-rule", "error": "boom"}])
    assert out["score_is_upper_bound"] is True
    assert out["compliant"] is False


# ── The two layers have to agree with each other ──────────────────────────────────────

def _report(files, sid="scopetest", scope=None):
    return {
        "_scan_id": sid,
        "rubric": {"name": "r", "version": "1", "hash": "h", "target": "AA"},
        "summary": {"files": len(files), "certifiable": 0, "uncertain": 0, "error": 0,
                    "avg_score": 60},
        "started_at": "2026-07-30T00:00:00+00:00",
        "completed_at": "2026-07-30T00:01:00+00:00",
        "source": "local", "owner": "scope@test", "files": files,
        # Phase 3a — a scan carries its OWN frozen scope (run_scan records scope_out here, with
        # scan_scope inside it). save_scan gates the traces from THIS, not the live setting. None
        # by default so the unscoped baseline stays unscoped.
        **({"scope": scope} if scope is not None else {}),
    }


def _file(name):
    """One document failing an out-of-scope criterion (1.4.11) and an in-scope one (1.1.1)."""
    return {"file": name, "engine": "python/pdf", "status": "analysed", "score": 60,
            "compliant": 0, "skipped_rules": 0, "checksum": "c1", "pii": None,
            "issues": [issue(OUT_OF_SCOPE), issue(IN_SCOPE_ALL)]}


# ── The wiring, through a real Store ──────────────────────────────────────────────────
# The unit tests above pass a scope to `_rule_outcome` directly, which proves the gate but NOT
# that anything resolves and threads one. That resolution is exactly what was missing, so it gets
# its own tests through the two paths that write traces.
#
# PHASE 3a moved the SOURCE of that scope from the live global setting to the scan's OWN frozen
# scope: save_scan reads report["scope"]["scan_scope"] (what run_scan recorded) and
# save_file_result reads store.get_scan_scope(scan_id) (what init_scan_run recorded). Both tests
# now set the live setting the OTHER way to prove the FROZEN scope — not the live one — is what
# gates.

# The 14-criterion preset in the JSON shape a scan records on itself.
_ENGAGEMENT_JSON = ap.scope_as_json(ap.SCOPE_PRESETS[ENGAGEMENT])


def test_save_scan_gates_the_traces_from_the_recorded_scan_scope(store):
    store.save_scan(_report([_file("unscoped.pdf")], sid="before"))
    before = {t["rule_id"]: t["outcome"] for t in store.get_scan_traces("before")}
    assert before["1.4.11"] == "FAIL", "baseline: an unscoped save records the finding"
    assert before["1.1.1"] == "FAIL"

    # Live global left UNSCOPED on purpose; the scope is frozen on the scan itself.
    store.set_setting(ap.SCOPE_SETTING, "")
    store.save_scan(_report([_file("scoped.pdf")], sid="after",
                            scope={"kind": "local", "kept": 1, "scan_scope": _ENGAGEMENT_JSON}))
    after = {t["rule_id"]: t["outcome"] for t in store.get_scan_traces("after")}
    assert after["1.4.11"] == ap.NOT_EVALUATED, (
        "save_scan did not thread the scan's FROZEN scope into _rule_outcome — the recorded "
        "scan_scope gated nothing, which is the defect the 3a wiring must prevent")
    assert after["1.1.1"] == "FAIL", "an in-scope criterion must still fail"


def test_save_file_result_gates_the_traces_from_the_recorded_scan_scope(store):
    """The per-file path is a separate call site and reads the scan's frozen scope separately."""
    # Live global left UNSCOPED; the frozen scope is what init_scan_run recorded on this scan.
    store.set_setting(ap.SCOPE_SETTING, "")
    store.init_scan_run("perfile", "local", 1, "2026-07-30T00:00:00+00:00", "rubric", "hash",
                        scope={"kind": "local", "kept": 1, "scan_scope": _ENGAGEMENT_JSON})
    store.save_file_result("perfile", _file("one.pdf"), "2026-07-30T00:01:00+00:00")
    tr = {t["rule_id"]: t["outcome"] for t in store.get_scan_traces("perfile")}
    assert tr["1.4.11"] == ap.NOT_EVALUATED
    assert tr["1.1.1"] == "FAIL"


def test_the_findings_themselves_are_still_stored_under_a_scope(store):
    """A scope changes what is ASSESSED, not what was observed — so re-scoping needs no re-scan.

    If the gate dropped findings at the storage layer instead, narrowing the scope would destroy
    evidence and widening it again would silently report fewer failures than the scan found.
    """
    store.save_scan(_report([_file("kept.pdf")],
                            scope={"kind": "local", "kept": 1, "scan_scope": _ENGAGEMENT_JSON}))
    scan = store.get_scan("scopetest")
    stored = [i["wcag"] for f in scan["files"] for i in (f.get("issues") or [])]
    assert "SC_1_4_11" in stored, "the out-of-scope finding was dropped from the record"
    assert "SC_1_1_1" in stored


def test_traces_and_score_agree_about_every_scoped_pair(scoped):
    """The invariant both defects broke: a criterion the trace calls NOT_EVALUATED must not be
    carrying a score penalty, and one the trace calls FAIL must be."""
    rb = rubric()
    for sc in sorted(set(ap.SCOPE_PRESETS[ENGAGEMENT]) | {OUT_OF_SCOPE, "1.4.4", "3.3.2"}):
        for fmt in ("docx", "xlsx", "pptx", "pdf"):
            one = [issue(sc)]
            outcome = ap._rule_outcome(sc, fmt, 1, 0, "AA", scoped)
            penalised = rb.assess(True, ap.filter_issues_to_scope(one, fmt, scoped), [])
            counted = penalised["score"] < 100
            if outcome == ap.NOT_EVALUATED:
                assert not counted, f"{sc} x {fmt}: trace says NOT_EVALUATED but the score paid for it"
            elif outcome == "FAIL":
                assert counted, f"{sc} x {fmt}: trace says FAIL but the score ignored it"
