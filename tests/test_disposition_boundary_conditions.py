"""Boundary conditions for disposition.matches() — exact-value edge cases.

Pure unit tests: no DB, no monkeypatching, no fixtures.  The operators are
lambdas in _OPS; these tests pin exactly which side of the boundary each
one includes/excludes.

Covered:
  age_days (derived from created_at):
    gt N  at N → False   (strictly greater, so equal is not a match)
    gt N  at N+1 → True
    gte N at N → True    (inclusive)
    lt N  at N → False
    lte N at N → True

  modified_age_days (derived from source_modified): same four shapes

  size_kb (stored as-is):
    gt / gte / lt / lte at the exact stored value

  parent_folder (derived from path via posixpath.dirname):
    prefix match on the folder, not the full path
    case-insensitive prefix
    no match when predicate is the full file path
    no parent_folder when path has no directory component
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

from disposition import matches


def _days_ago(n: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=n)).isoformat()


# ── age_days boundary (derived from created_at) ───────────────────────────────

def test_age_days_gt_at_exact_value_does_not_match():
    doc = {"created_at": _days_ago(30)}
    assert not matches(doc, [{"field": "age_days", "op": "gt", "value": 30}])


def test_age_days_gt_one_below_matches():
    doc = {"created_at": _days_ago(30)}
    assert matches(doc, [{"field": "age_days", "op": "gt", "value": 29}])


def test_age_days_gte_at_exact_value_matches():
    doc = {"created_at": _days_ago(30)}
    assert matches(doc, [{"field": "age_days", "op": "gte", "value": 30}])


def test_age_days_gte_one_above_does_not_match():
    doc = {"created_at": _days_ago(30)}
    assert not matches(doc, [{"field": "age_days", "op": "gte", "value": 31}])


def test_age_days_lt_at_exact_value_does_not_match():
    doc = {"created_at": _days_ago(30)}
    assert not matches(doc, [{"field": "age_days", "op": "lt", "value": 30}])


def test_age_days_lt_one_above_matches():
    doc = {"created_at": _days_ago(30)}
    assert matches(doc, [{"field": "age_days", "op": "lt", "value": 31}])


def test_age_days_lte_at_exact_value_matches():
    doc = {"created_at": _days_ago(30)}
    assert matches(doc, [{"field": "age_days", "op": "lte", "value": 30}])


def test_age_days_lte_one_below_does_not_match():
    doc = {"created_at": _days_ago(30)}
    assert not matches(doc, [{"field": "age_days", "op": "lte", "value": 29}])


# ── modified_age_days boundary (derived from source_modified) ─────────────────

def test_modified_age_days_gt_at_exact_value_does_not_match():
    doc = {"source_modified": _days_ago(30)}
    assert not matches(doc, [{"field": "modified_age_days", "op": "gt", "value": 30}])


def test_modified_age_days_gt_one_below_matches():
    doc = {"source_modified": _days_ago(30)}
    assert matches(doc, [{"field": "modified_age_days", "op": "gt", "value": 29}])


def test_modified_age_days_gte_at_exact_value_matches():
    doc = {"source_modified": _days_ago(30)}
    assert matches(doc, [{"field": "modified_age_days", "op": "gte", "value": 30}])


def test_modified_age_days_lte_at_exact_value_matches():
    doc = {"source_modified": _days_ago(30)}
    assert matches(doc, [{"field": "modified_age_days", "op": "lte", "value": 30}])


def test_modified_age_days_lt_at_exact_value_does_not_match():
    doc = {"source_modified": _days_ago(30)}
    assert not matches(doc, [{"field": "modified_age_days", "op": "lt", "value": 30}])


# ── size_kb boundary (stored value — no derivation) ───────────────────────────

def test_size_kb_gt_at_exact_value_does_not_match():
    assert not matches({"size_kb": 100}, [{"field": "size_kb", "op": "gt", "value": 100}])


def test_size_kb_gt_one_below_matches():
    assert matches({"size_kb": 100}, [{"field": "size_kb", "op": "gt", "value": 99}])


def test_size_kb_gte_at_exact_value_matches():
    assert matches({"size_kb": 100}, [{"field": "size_kb", "op": "gte", "value": 100}])


def test_size_kb_gte_one_above_does_not_match():
    assert not matches({"size_kb": 100}, [{"field": "size_kb", "op": "gte", "value": 101}])


def test_size_kb_lte_at_exact_value_matches():
    assert matches({"size_kb": 100}, [{"field": "size_kb", "op": "lte", "value": 100}])


def test_size_kb_lt_at_exact_value_does_not_match():
    assert not matches({"size_kb": 100}, [{"field": "size_kb", "op": "lt", "value": 100}])


# ── parent_folder derivation (posixpath.dirname of doc["path"]) ───────────────

def test_parent_folder_prefix_matches_directory():
    doc = {"path": "/Finance/Reports/q4.pdf"}
    assert matches(doc, [{"field": "parent_folder", "op": "prefix", "value": "/Finance/Reports"}])


def test_parent_folder_prefix_is_case_insensitive():
    doc = {"path": "/Finance/Reports/q4.pdf"}
    assert matches(doc, [{"field": "parent_folder", "op": "prefix", "value": "/finance/"}])


def test_parent_folder_eq_is_dirname_not_full_path():
    doc = {"path": "/Finance/Reports/q4.pdf"}
    # parent_folder = /Finance/Reports, NOT /Finance/Reports/q4.pdf
    assert matches(doc, [{"field": "parent_folder", "op": "eq", "value": "/Finance/Reports"}])
    assert not matches(doc, [{"field": "parent_folder", "op": "eq", "value": "/Finance/Reports/q4.pdf"}])


def test_parent_folder_prefix_does_not_match_sibling_directory():
    doc = {"path": "/Finance/Reports/q4.pdf"}
    # /Finance/Budgets is NOT a prefix of /Finance/Reports
    assert not matches(doc, [{"field": "parent_folder", "op": "prefix", "value": "/Finance/Budgets"}])


def test_parent_folder_absent_when_path_has_no_directory():
    # A file at the root level: dirname("/rootfile.pdf") = "/"
    doc = {"path": "/rootfile.pdf"}
    assert matches(doc, [{"field": "parent_folder", "op": "eq", "value": "/"}])


def test_parent_folder_none_when_path_missing():
    doc = {}
    # No path → parent_folder is None → eq predicate returns False, not an error
    assert not matches(doc, [{"field": "parent_folder", "op": "eq", "value": "/Finance"}])
