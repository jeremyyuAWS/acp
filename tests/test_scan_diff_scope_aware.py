"""A scan diff must not report a scope change as progress (ADR 0009).

TWO FAILURES, ONE CAUSE. A score is computed over the IN-SCOPE findings, so the same unchanged
document scores 60 under a wide scope and 75 with one criterion in scope. Diff those two scans
and:

  - every document reads as IMPROVED. An operator who narrowed the scope is congratulated on
    progress that did not happen. That is worse than a missing feature, because it is believed
    and it is the number that goes in a status report.
  - every file whose format the new scope excludes was never read, so it is absent from
    file_records and lands in `removed` — "45 documents disappeared".

Neither is a change in the estate. Both were reported as one.

THE COMPARISON IS PER FORMAT, NOT GLOBAL. A scope change that only touched PDF criteria leaves
every .docx score computed over exactly the same criteria as before, so those deltas are real.
Treating any scope change as poisoning the whole diff would discard the comparison an operator
most often wants, which is the failure mode of the obvious fix.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))

import assessment_policy as pol  # noqa: E402

WIDE = {"1.1.1": ["docx", "pdf"], "1.3.1": ["docx"], "1.4.3": ["pdf"]}
DOCX_ONLY = {"1.1.1": ["docx"], "1.3.1": ["docx"]}
DOCX_NARROWER = {"1.1.1": ["docx"]}                       # 1.3.1 dropped for docx


# ── the helpers the diff is built on ──────────────────────────────────────────

def test_scope_serialises_canonically():
    """Two equal scopes must serialise identically, or the diff sees a change that never
    happened — a frozenset's iteration order is not stable across processes."""
    a = pol.scope_as_json({"1.3.1": frozenset({"docx", "pdf"}), "1.1.1": frozenset({"docx"})})
    b = pol.scope_as_json({"1.1.1": frozenset({"docx"}), "1.3.1": frozenset({"pdf", "docx"})})
    assert a == b
    assert list(a) == ["1.1.1", "1.3.1"], "criteria must be ordered"
    assert a["1.3.1"] == ["docx", "pdf"], "formats must be ordered"


def test_scope_as_json_keeps_unset_distinguishable():
    assert pol.scope_as_json(None) is None
    assert pol.scope_as_json({}) is None


def test_criteria_for_format_is_per_format():
    assert pol.criteria_for_format(WIDE, "docx") == frozenset({"1.1.1", "1.3.1"})
    assert pol.criteria_for_format(WIDE, "pdf") == frozenset({"1.1.1", "1.4.3"})
    assert pol.criteria_for_format(None, "docx") is None


def test_dropping_pdf_criteria_leaves_docx_comparable():
    """THE case the per-format comparison exists for. Stopping PDF scanning must not invalidate
    every Word document's score history."""
    assert (pol.criteria_for_format(WIDE, "docx")
            == pol.criteria_for_format(DOCX_ONLY, "docx"))
    assert (pol.criteria_for_format(WIDE, "pdf")
            != pol.criteria_for_format(DOCX_ONLY, "pdf"))


def test_dropping_a_docx_criterion_makes_docx_incomparable():
    assert (pol.criteria_for_format(DOCX_ONLY, "docx")
            != pol.criteria_for_format(DOCX_NARROWER, "docx"))


# ── the diff ──────────────────────────────────────────────────────────────────

# conftest's `isolated_store`, not a hand-rolled one. The first version of this file set an
# ACP_DB env var and reloaded the module; neither is how this repo isolates a Store, so every
# test in the file shared one database and read the PREVIOUS test's scan_runs rows — which
# presents as `scope_changed` being True for two scans that recorded the same scope. conftest
# also warns against the reload specifically: it swaps the module object out from under anything
# that did `from store import ...`.
@pytest.fixture
def store(isolated_store):
    return isolated_store


def _seed(st, scan_id, scope_json, files, when):
    """One completed scan: its recorded scope plus a score per file.

    Written through `init_scan_run` / `save_file_result` rather than raw SQL, so the rows are
    the shape a real scan produces — a hand-built row can satisfy a diff that the product could
    never actually feed.
    """
    st.init_scan_run(scan_id, "drive", len(files), when, "default", "rh",
                     owner="a@example.com", status="running",
                     scope={"kind": "drive", "kept": len(files), "scan_scope": scope_json})
    for name, score in files.items():
        st.save_file_result(scan_id, {"file": name, "engine": ".net/office",
                                      "status": "analysed", "score": score,
                                      "compliant": 0, "skipped_rules": 0, "issues": []}, when)
    with st._db.cursor() as cur:
        st._db.execute(cur, "UPDATE scan_runs SET completed_at=%s WHERE id=%s", (when, scan_id))


def test_narrowing_the_scope_is_not_reported_as_improvement(store):
    """The headline. Same documents, same bytes, higher scores because fewer criteria count."""
    _seed(store, "s1", WIDE, {"a.docx": 60, "b.docx": 55}, "2026-08-01T00:00:00Z")
    _seed(store, "s2", DOCX_NARROWER, {"a.docx": 75, "b.docx": 70}, "2026-08-02T00:00:00Z")

    d = store.get_scan_diff("s2", "s1", owner="a@example.com")
    assert d is not None
    assert d["scope_changed"] is True
    assert d["summary"]["improved"] == 0, (
        f"a scope change was reported as improvement: {d['improved']}")
    assert d["summary"]["incomparable"] == 2
    assert d["incomparable"][0]["reason"]


def test_a_real_regression_still_shows_when_the_scope_held(store):
    """The control. Without this the test above passes for a diff that reports nothing ever."""
    _seed(store, "s1", DOCX_ONLY, {"a.docx": 90}, "2026-08-01T00:00:00Z")
    _seed(store, "s2", DOCX_ONLY, {"a.docx": 60}, "2026-08-02T00:00:00Z")

    d = store.get_scan_diff("s2", "s1", owner="a@example.com")
    assert d["scope_changed"] is False
    assert d["summary"]["regressed"] == 1
    assert d["regressed"][0]["delta"] == -30


def test_dropping_pdfs_keeps_docx_deltas_comparable(store):
    """A scope change that only touched PDF criteria must not invalidate Word history."""
    _seed(store, "s1", WIDE, {"a.docx": 90, "x.pdf": 80}, "2026-08-01T00:00:00Z")
    _seed(store, "s2", DOCX_ONLY, {"a.docx": 60}, "2026-08-02T00:00:00Z")

    d = store.get_scan_diff("s2", "s1", owner="a@example.com")
    assert d["scope_changed"] is True
    assert d["summary"]["regressed"] == 1, "the .docx regression is real and must still report"
    assert d["regressed"][0]["file"] == "a.docx"


def test_a_file_the_scope_excluded_is_not_read_not_removed(store):
    """"We did not look" and "it is gone" are different facts, and only one is about the estate."""
    _seed(store, "s1", WIDE, {"a.docx": 90, "x.pdf": 80}, "2026-08-01T00:00:00Z")
    _seed(store, "s2", DOCX_ONLY, {"a.docx": 90}, "2026-08-02T00:00:00Z")

    d = store.get_scan_diff("s2", "s1", owner="a@example.com")
    assert d["summary"]["removed"] == 0, "an out-of-scope file did not disappear from the estate"
    assert d["summary"]["not_read"] == 1
    assert d["not_read"][0]["file"] == "x.pdf"


def test_a_genuinely_missing_file_is_still_removed(store):
    """The control for the split. A file whose format IS in scope and is absent really is gone."""
    _seed(store, "s1", DOCX_ONLY, {"a.docx": 90, "b.docx": 80}, "2026-08-01T00:00:00Z")
    _seed(store, "s2", DOCX_ONLY, {"a.docx": 90}, "2026-08-02T00:00:00Z")

    d = store.get_scan_diff("s2", "s1", owner="a@example.com")
    assert d["summary"]["removed"] == 1
    assert d["removed"][0]["file"] == "b.docx"
    assert d["summary"]["not_read"] == 0


def test_scans_predating_the_field_still_diff(store):
    """`scan_scope` absent means "no restriction" — the only reading available, and the same one
    formats_in_scope gives. A diff must not break on history recorded before this existed."""
    _seed(store, "s1", None, {"a.docx": 90}, "2026-08-01T00:00:00Z")
    _seed(store, "s2", None, {"a.docx": 60}, "2026-08-02T00:00:00Z")

    d = store.get_scan_diff("s2", "s1", owner="a@example.com")
    assert d["scope_changed"] is False
    assert d["summary"]["regressed"] == 1
