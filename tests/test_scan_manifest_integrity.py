"""The per-rule execution manifest must never certify work it did not do.

WHAT THIS TABLE WAS DOING, measured against a real Store on 2026-09-01 rather than read off the
source. A .docx the engine could not open — no issues, one whole-file error — was recorded as:

    17 PASS · 0 ERROR · completeness 100% · complete: true

and a second file whose extension has no catalog rules did not appear in the manifest at all, so
a two-file scan reported files_total 1.

Two independent causes, both structural:

  * `errors` IS NOT ON THE FILE DICT ON THE PRODUCTION PATH. Rubric.assess (scripts/rubric.py:55)
    consumes the engine's error list and returns `status` + `skipped_rules` in its place;
    scanner.analyse_and_assess builds the record from `**assessed`. So `f["errors"]` was empty on
    every production write, `_save_file_manifest`'s ERROR branch was unreachable, and
    `rules_errored_total` was structurally 0 — which made `complete` (errored == 0) structurally
    true for every scan this table has ever held. The /scans/{sid}/manifest docstring's promise,
    "A scan is COMPLETE when rules_errored_total == 0. Use this to detect partial assessments
    before acting on a score", could not fire.
  * The `else: status = "PASS"` default. A rule nothing said anything about was a pass.

There were no tests for get_scan_manifest at all, which is how both survived.

The rule these tests exist to hold: "we did not look" and "we looked and found nothing" are
different claims, and only the second may be certified.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))
sys.path.insert(0, str(ACP / "scripts"))

import store as store_mod  # noqa: E402

CATALOG = store_mod._CATALOG_JSON
DOCX_RULES = [r["id"] for r in CATALOG.get("docx", [])]


def _write(st, scan_id: str, f: dict) -> None:
    """Persist one file exactly as a scan does: a file_records row plus its manifest rows."""
    with st._db.cursor() as cur:
        st._db.execute(cur,
            "INSERT INTO file_records(scan_id,file,engine,status,score,compliant,skipped_rules) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s)",
            (scan_id, f["file"], f.get("engine", "test"), f.get("status"), f.get("score"),
             int(bool(f.get("compliant"))), f.get("skipped_rules", 0)))
        st._save_file_manifest(cur, scan_id, f, CATALOG)


def _statuses(entry: dict) -> dict[str, int]:
    """Per-rule status tally for one file, excluding the other formats' NOT_APPLICABLE noise."""
    out: dict[str, int] = {}
    for r in entry["rules"]:
        if r["status"] != "NOT_APPLICABLE":
            out[r["status"]] = out.get(r["status"], 0) + 1
    return out


def _file(manifest: dict, name: str) -> dict:
    matches = [f for f in manifest["files"] if f["file"] == name]
    assert matches, f"{name} is missing from the manifest entirely"
    return matches[0]


# ── the defect ────────────────────────────────────────────────────────────────────────────
def test_a_file_the_engine_could_not_open_is_not_recorded_as_passing(isolated_store):
    """THE regression. Every rule was PASS on a document nothing read."""
    _write(isolated_store, "S", {
        "file": "broken.docx", "status": "error", "score": None, "skipped_rules": 1,
        "issues": [], "errors": [{"message": "could not open", "rule": None}]})

    entry = _file(isolated_store.get_scan_manifest("S"), "broken.docx")
    assert _statuses(entry) == {"NOT_CHECKED": len(DOCX_RULES)}
    assert "PASS" not in _statuses(entry)
    assert entry["completeness_pct"] == 0
    assert entry["complete"] is False


def test_the_run_is_not_complete_when_a_file_was_never_analysed(isolated_store):
    """`complete` was `rules_errored_total == 0`, and with the ERROR branch unreachable that was
    true of every scan regardless of what happened during it."""
    _write(isolated_store, "S", {"file": "ok.docx", "status": "analysed", "score": 100,
                                 "skipped_rules": 0, "issues": [], "errors": []})
    _write(isolated_store, "S", {"file": "broken.docx", "status": "error", "score": None,
                                 "skipped_rules": 1, "issues": [], "errors": []})

    m = isolated_store.get_scan_manifest("S")
    assert m["complete"] is False
    assert m["rules_not_checked_total"] == len(DOCX_RULES)
    assert m["completeness_pct"] < 100


def test_a_production_shaped_record_carries_no_error_list_and_still_is_not_certified(isolated_store):
    """The shape the fan-out path actually writes: Rubric.assess's fields, no `errors` key.

    This is the case the old code could not catch by construction — with no error list there was
    nothing to mark ERROR, so the whole catalog defaulted to PASS. `status` was there the whole
    time and is what is read now.
    """
    from rubric import Rubric
    assessed = Rubric.load_active(ACP / "config").assess(
        False, [], [{"message": "could not open", "rule": None}])
    assert "errors" not in assessed, "if assess() starts returning errors, revisit scanner.py"

    _write(isolated_store, "S", {"file": "broken.docx", "engine": ".net/office",
                                 "issues": [], **assessed})
    entry = _file(isolated_store.get_scan_manifest("S"), "broken.docx")
    assert _statuses(entry) == {"NOT_CHECKED": len(DOCX_RULES)}


def test_a_deliberately_skipped_file_is_also_not_recorded_as_passing(isolated_store):
    """A shadow of ACP's own output is skipped on purpose (handlers.py). Not analysed either."""
    _write(isolated_store, "S", {"file": "shadow.docx", "status": "skipped", "score": None,
                                 "skipped_rules": 0, "issues": [], "errors": []})
    entry = _file(isolated_store.get_scan_manifest("S"), "shadow.docx")
    assert _statuses(entry) == {"NOT_CHECKED": len(DOCX_RULES)}
    assert entry["file_status"] == "skipped"


# ── the file that vanished ────────────────────────────────────────────────────────────────
def test_a_file_with_no_manifest_rows_is_reported_rather_than_dropped(isolated_store):
    """The file list used to be `SELECT DISTINCT file FROM scan_file_manifests` — which defines
    the scan's files as the files that have rows, so one with none was absent rather than 0%."""
    _write(isolated_store, "S", {"file": "ok.docx", "status": "analysed", "score": 100,
                                 "skipped_rules": 0, "issues": [], "errors": []})
    _write(isolated_store, "S", {"file": "notes.txt", "status": "analysed", "score": 100,
                                 "skipped_rules": 0, "issues": [], "errors": []})

    m = isolated_store.get_scan_manifest("S")
    assert m["files_total"] == 2
    assert {f["file"] for f in m["files"]} == {"ok.docx", "notes.txt"}


def test_an_unsupported_format_says_so_and_does_not_count_against_completeness(isolated_store):
    """Nothing was ever expected of a .txt, so it is neither complete nor incomplete — it is out
    of scope. Counting it as a gap would make every mixed estate permanently un-certifiable."""
    _write(isolated_store, "S", {"file": "ok.docx", "status": "analysed", "score": 100,
                                 "skipped_rules": 0, "issues": [], "errors": []})
    _write(isolated_store, "S", {"file": "notes.txt", "status": "analysed", "score": 100,
                                 "skipped_rules": 0, "issues": [], "errors": []})

    m = isolated_store.get_scan_manifest("S")
    assert _file(m, "notes.txt")["reason"] == "unsupported_format"
    assert m["completeness_pct"] == 100 and m["complete"] is True
    assert m["rules_expected_total"] == len(DOCX_RULES)   # the .txt added no expectation


def test_a_supported_file_with_no_rows_is_an_integrity_fault_not_an_empty_pass(isolated_store):
    """A .docx whose manifest was never written expected its whole catalog. Reporting it as an
    empty, complete file is the same lie as PASS, one level up."""
    with isolated_store._db.cursor() as cur:
        isolated_store._db.execute(cur,
            "INSERT INTO file_records(scan_id,file,engine,status,score,compliant,skipped_rules) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s)", ("S", "lost.docx", "test", "analysed", 100, 1, 0))

    entry = _file(isolated_store.get_scan_manifest("S"), "lost.docx")
    assert entry["reason"] == "no_manifest"
    assert entry["rules_expected"] == len(DOCX_RULES)
    assert entry["completeness_pct"] == 0
    assert entry["complete"] is False


def test_the_missing_rules_of_a_lost_file_are_named_not_swept_into_not_applicable(isolated_store):
    """The summary and the per-rule list have to be the same answer.

    With no rows to read, every rule fell into the NOT_APPLICABLE sweep — so the counts said
    '17 checks did not run' while the list beside them said all 70 were not applicable, and the
    UI's named-checks disclosure showed nothing for the very file it was about. A gap you cannot
    name is one nobody can act on.
    """
    with isolated_store._db.cursor() as cur:
        isolated_store._db.execute(cur,
            "INSERT INTO file_records(scan_id,file,engine,status,score,compliant,skipped_rules) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s)", ("S", "lost.docx", "test", "analysed", 100, 1, 0))

    entry = _file(isolated_store.get_scan_manifest("S"), "lost.docx")
    named = {r["rule_id"] for r in entry["rules"] if r["status"] == "NOT_CHECKED"}
    assert named == set(DOCX_RULES)
    # ...and none of them is ALSO claimed as not-applicable.
    na = {r["rule_id"] for r in entry["rules"] if r["status"] == "NOT_APPLICABLE"}
    assert named.isdisjoint(na)
    assert entry["rules_not_checked"] == len(DOCX_RULES)


# ── the four statuses, kept apart ─────────────────────────────────────────────────────────
def test_an_attributable_rule_error_records_error_and_is_reachable_at_all(isolated_store):
    """`rules_errored_total` was structurally 0 because nothing could ever be marked ERROR."""
    rid = DOCX_RULES[0]
    _write(isolated_store, "S", {"file": "partial.docx", "status": "uncertain", "score": 90,
                                 "skipped_rules": 1, "issues": [],
                                 "errors": [{"message": "boom", "rule": rid}]})

    m = isolated_store.get_scan_manifest("S")
    assert m["rules_errored_total"] == 1
    errored = [r for r in _file(m, "partial.docx")["rules"] if r["status"] == "ERROR"]
    assert [r["rule_id"] for r in errored] == [rid]
    assert m["complete"] is False


def test_a_finding_is_a_fail_and_is_still_evidence_the_rule_ran(isolated_store):
    rid = DOCX_RULES[0]
    _write(isolated_store, "S", {"file": "found.docx", "status": "analysed", "score": 80,
                                 "skipped_rules": 0,
                                 "issues": [{"ruleId": rid, "wcag": "1.1.1", "severity": "SERIOUS"}],
                                 "errors": []})
    m = isolated_store.get_scan_manifest("S")
    tally = _statuses(_file(m, "found.docx"))
    assert tally == {"FAIL": 1, "PASS": len(DOCX_RULES) - 1}
    # A FAIL is a completed check: a scan that found problems is still a complete scan.
    assert m["complete"] is True and m["completeness_pct"] == 100


def test_rules_from_another_format_stay_not_applicable_and_are_not_a_gap(isolated_store):
    _write(isolated_store, "S", {"file": "ok.docx", "status": "analysed", "score": 100,
                                 "skipped_rules": 0, "issues": [], "errors": []})
    m = isolated_store.get_scan_manifest("S")
    entry = _file(m, "ok.docx")
    assert entry["rules_not_applicable"] > 0
    assert m["rules_not_applicable_total"] == entry["rules_not_applicable"]
    assert m["complete"] is True          # N/A never counts against completeness


# ── errors the rubric counted but no row names ────────────────────────────────────────────
def test_an_unattributed_error_count_is_reported_rather_than_resolved_to_pass(isolated_store):
    """file_records.skipped_rules survives where the error LIST does not. Two errors with no
    names is 'two rules errored and which ones was not recorded' — not 'everything passed'."""
    _write(isolated_store, "S", {"file": "legacy.docx", "status": "uncertain", "score": 90,
                                 "skipped_rules": 2, "issues": [], "errors": []})

    m = isolated_store.get_scan_manifest("S")
    assert m["rules_errored_unattributed_total"] == 2
    assert m["rules_checked_total"] == len(DOCX_RULES) - 2
    assert m["complete"] is False


def test_an_unattributed_count_is_not_double_counted_on_a_file_that_never_ran(isolated_store):
    """Every rule is already NOT_CHECKED there, so the rubric's count describes the same gap.
    Counting it twice would report more missing rules than the file has."""
    _write(isolated_store, "S", {"file": "broken.docx", "status": "error", "score": None,
                                 "skipped_rules": 5, "issues": [], "errors": []})
    entry = _file(isolated_store.get_scan_manifest("S"), "broken.docx")
    assert entry["rules_errored_unattributed"] == 0
    assert entry["rules_not_checked"] == len(DOCX_RULES)


# ── the whole thing has to add up ─────────────────────────────────────────────────────────
def test_the_totals_reconcile_across_a_mixed_scan(isolated_store):
    """checked + errored + not_checked + unattributed == expected, on a scan with one of each.

    Rendered arithmetic is the point: a gate whose numbers do not sum invites an argument about
    the numbers instead of about the documents.
    """
    rid = DOCX_RULES[0]
    for f in (
        {"file": "good.docx", "status": "analysed", "score": 100, "skipped_rules": 0,
         "issues": [], "errors": []},
        {"file": "broken.docx", "status": "error", "score": None, "skipped_rules": 1,
         "issues": [], "errors": []},
        {"file": "partial.docx", "status": "uncertain", "score": 90, "skipped_rules": 1,
         "issues": [], "errors": [{"message": "boom", "rule": rid}]},
        {"file": "legacy.docx", "status": "uncertain", "score": 90, "skipped_rules": 2,
         "issues": [], "errors": []},
        {"file": "notes.txt", "status": "analysed", "score": 100, "skipped_rules": 0,
         "issues": [], "errors": []},
    ):
        _write(isolated_store, "S", f)

    m = isolated_store.get_scan_manifest("S")
    assert (m["rules_checked_total"] + m["rules_errored_total"]
            + m["rules_not_checked_total"] + m["rules_errored_unattributed_total"]
            == m["rules_expected_total"])
    assert m["files_total"] == 5
    assert m["complete"] is False


def test_a_genuinely_clean_scan_is_complete_and_says_so(isolated_store):
    """The gate has to be able to clear a run, or it is just a permanent warning."""
    for name in ("a.docx", "b.docx"):
        _write(isolated_store, "S", {"file": name, "status": "analysed", "score": 100,
                                     "skipped_rules": 0, "issues": [], "errors": []})
    m = isolated_store.get_scan_manifest("S")
    assert m["complete"] is True
    assert m["completeness_pct"] == 100
    assert m["rules_errored_total"] == 0
    assert m["rules_not_checked_total"] == 0
    assert m["rules_errored_unattributed_total"] == 0
    assert m["rules_checked_total"] == m["rules_expected_total"] == 2 * len(DOCX_RULES)


def test_an_empty_scan_is_not_reported_as_a_complete_one(isolated_store):
    """Nothing to check is not the same as everything checked — but it is also not a fault, so
    it stays complete-with-zero rather than inventing a failure. Pinned so the arithmetic on an
    empty scan is a decision rather than a division-by-zero accident."""
    m = isolated_store.get_scan_manifest("S")
    assert m["files_total"] == 0
    assert m["rules_expected_total"] == 0
    assert m["completeness_pct"] == 100


@pytest.mark.parametrize("status", ["error", "skipped"])
def test_every_non_analysed_status_defaults_to_not_checked(isolated_store, status):
    _write(isolated_store, "S", {"file": f"{status}.docx", "status": status, "score": None,
                                 "skipped_rules": 0, "issues": [], "errors": []})
    entry = _file(isolated_store.get_scan_manifest("S"), f"{status}.docx")
    assert entry["rules_not_checked"] == len(DOCX_RULES)
