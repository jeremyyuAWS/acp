"""Criterion disposition persistence — W4 backend tests.

WHAT THIS TESTS. The W4 lane lets a reviewer record a human resolution for a criterion
that reached a terminal state (UNCHECKED / GAP / AT) without a fix.  Two backend routes
and one store method carry this:

  POST /scans/{sid}/files/{file}/dispose   — record a disposition (immutable, append-only)
  GET  /scans/{sid}/files/{file}/dispositions — list dispositions for a file

STRUCTURE.
  - store unit tests: happy path, validation, append-only, owner scoping
  - structural tests: routes exist in scans.py, dual-write to decision_log, table in schema
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

import store as store_mod  # noqa: E402

ACP = Path(__file__).resolve().parent.parent


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def st(monkeypatch):
    monkeypatch.setattr(store_mod, "_SQLITE_PATH", Path(tempfile.mkdtemp()) / "disp.db")
    s = store_mod.Store()
    s.init_scan_run("s1", "drive", 1, "t0", "r", "h")
    return s


# ── store.record_criterion_disposition ───────────────────────────────────────

def test_record_returns_a_row_with_all_fields(st):
    row = st.record_criterion_disposition("s1", "f.docx", "1.1.1", "attested",
                                          "verified out-of-band via screen reader", "alice@x.com")
    assert row["sc"] == "1.1.1"
    assert row["kind"] == "attested"
    assert row["reason"] == "verified out-of-band via screen reader"
    assert row["actor"] == "alice@x.com"
    assert row["id"]
    assert row["ts"]


def test_record_out_of_scope_kind(st):
    row = st.record_criterion_disposition("s1", "f.docx", "2.4.6", "out_of_scope",
                                          "not in engagement scope per SOW", "bob@x.com")
    assert row["kind"] == "out_of_scope"


def test_record_rejects_unknown_kind(st):
    with pytest.raises(ValueError, match="unknown disposition kind"):
        st.record_criterion_disposition("s1", "f.docx", "1.1.1", "deleted",
                                        "some reason", "alice@x.com")


def test_record_is_append_only(st):
    """A second disposition for the same criterion adds a new row; nothing is updated."""
    st.record_criterion_disposition("s1", "f.docx", "1.1.1", "attested",
                                    "first pass", "alice@x.com")
    st.record_criterion_disposition("s1", "f.docx", "1.1.1", "out_of_scope",
                                    "correction — actually out of scope", "alice@x.com")
    rows = st.list_criterion_dispositions("s1", "f.docx")
    assert len(rows) == 2, "both rows must be preserved; nothing was updated"


def test_list_returns_most_recent_first(st):
    st.record_criterion_disposition("s1", "f.docx", "1.1.1", "attested",
                                    "first", "alice@x.com")
    st.record_criterion_disposition("s1", "f.docx", "1.1.1", "out_of_scope",
                                    "second", "alice@x.com")
    rows = st.list_criterion_dispositions("s1", "f.docx")
    assert rows[0]["reason"] == "second"
    assert rows[1]["reason"] == "first"


def test_list_returns_all_criteria_for_file(st):
    st.record_criterion_disposition("s1", "f.docx", "1.1.1", "attested", "r1", "a@x.com")
    st.record_criterion_disposition("s1", "f.docx", "2.4.6", "out_of_scope", "r2", "a@x.com")
    rows = st.list_criterion_dispositions("s1", "f.docx")
    scs = {r["sc"] for r in rows}
    assert scs == {"1.1.1", "2.4.6"}


def test_list_returns_empty_when_no_dispositions(st):
    rows = st.list_criterion_dispositions("s1", "f.docx")
    assert rows == []


def test_list_owner_scoping_filters_other_owners(st):
    """Owner-scoped query hides another owner's dispositions."""
    st.record_criterion_disposition("s1", "f.docx", "1.1.1", "attested",
                                    "alice's note", "alice@x.com", owner="alice@x.com")
    st.record_criterion_disposition("s1", "f.docx", "1.1.1", "out_of_scope",
                                    "bob's note", "bob@x.com", owner="bob@x.com")

    alice_rows = st.list_criterion_dispositions("s1", "f.docx", owner="alice@x.com")
    assert len(alice_rows) == 1
    assert alice_rows[0]["actor"] == "alice@x.com"

    bob_rows = st.list_criterion_dispositions("s1", "f.docx", owner="bob@x.com")
    assert len(bob_rows) == 1
    assert bob_rows[0]["actor"] == "bob@x.com"


def test_list_unscoped_returns_all_owners(st):
    st.record_criterion_disposition("s1", "f.docx", "1.1.1", "attested",
                                    "alice", "alice@x.com", owner="alice@x.com")
    st.record_criterion_disposition("s1", "f.docx", "2.4.6", "out_of_scope",
                                    "bob", "bob@x.com", owner="bob@x.com")
    rows = st.list_criterion_dispositions("s1", "f.docx")
    assert len(rows) == 2


def test_list_is_file_scoped(st):
    """Dispositions from a different file do not appear in the listing."""
    st.record_criterion_disposition("s1", "f.docx", "1.1.1", "attested", "r", "a@x.com")
    rows = st.list_criterion_dispositions("s1", "other.docx")
    assert rows == []


# ── structural: routes exist in scans.py ──────────────────────────────────────

def _scans_src() -> str:
    return (ACP / "api" / "routes" / "scans.py").read_text()


def test_dispose_post_route_exists():
    assert "files/{filename:path}/dispose" in _scans_src(), (
        "POST .../files/{filename:path}/dispose must be registered in api/routes/scans.py")


def test_dispositions_get_route_exists():
    assert "files/{filename:path}/dispositions" in _scans_src(), (
        "GET .../files/{filename:path}/dispositions must be registered in api/routes/scans.py")


def test_dispose_route_calls_record_criterion_disposition():
    assert "record_criterion_disposition" in _scans_src(), (
        "dispose route must call store.record_criterion_disposition")


def test_dispose_route_dual_writes_to_decision_log():
    """The route must write to decision_log so the audit trail captures the disposition.
    Pattern: every mutation in scans.py ends with a log_decision call."""
    src = _scans_src()
    # Find the dispose function body
    fn_start = src.index("async def dispose_criterion(")
    try:
        fn_end = src.index("\n@router.", fn_start)
    except ValueError:
        fn_end = len(src)
    fn_body = src[fn_start:fn_end]
    assert "log_decision" in fn_body, (
        "dispose_criterion must call store.log_decision for the audit trail")
    assert "criterion.disposed" in fn_body, (
        "dispose_criterion must log the 'criterion.disposed' action")


def test_dispositions_get_route_calls_list_criterion_dispositions():
    assert "list_criterion_dispositions" in _scans_src(), (
        "dispositions GET route must call store.list_criterion_dispositions")


# ── structural: table and methods exist in store.py ──────────────────────────

def _store_src() -> str:
    return (ACP / "api" / "store.py").read_text()


def test_criterion_disposition_table_created():
    assert "criterion_disposition" in _store_src(), (
        "store.py must CREATE TABLE criterion_disposition")


def test_record_criterion_disposition_method_exists():
    assert "def record_criterion_disposition(" in _store_src()


def test_list_criterion_dispositions_method_exists():
    assert "def list_criterion_dispositions(" in _store_src()


def test_store_knows_both_valid_kinds():
    """Both 'attested' and 'out_of_scope' must be in _DISPOSITION_KINDS."""
    src = _store_src()
    assert '"attested"' in src or "'attested'" in src
    assert '"out_of_scope"' in src or "'out_of_scope'" in src


# ── decision_log dual-write integration ──────────────────────────────────────

def test_decision_log_entry_is_written_on_disposition(st):
    """record_criterion_disposition alone does NOT write to decision_log — the ROUTE does.
    This test verifies the log_decision call from the route perspective by calling the store
    method directly (as the route does) and then the log_decision call separately, confirming
    that the decision_log table records the right action when the route pattern is followed."""
    st.record_criterion_disposition("s1", "f.docx", "1.1.1", "attested",
                                    "verified", "alice@x.com", owner="alice@x.com")
    st.log_decision("alice@x.com", "criterion.disposed", scan_id="s1",
                    file="f.docx", rule_id="1.1.1", detail="attested: verified")

    decisions = st.list_decisions(scan_id="s1")
    assert any(d["action"] == "criterion.disposed" and d["rule_id"] == "1.1.1"
               for d in decisions), (
        "criterion.disposed decision must appear in the decision log")
