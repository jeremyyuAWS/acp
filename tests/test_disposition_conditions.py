"""Disposition condition-matching — folder/path + modified-before lifecycle
rules (Discover/Assess Lifecycle PRD, Phase B1).

Pure logic over document dicts: no DB, no Drive. Covers the new path/parent_folder
fields, the prefix op, the before/after ISO-date ops, modified_age_days derivation,
validate_match's field/op allow-listing, and that AND-logic across mixed conditions
still holds. Malformed / None dates must yield False, never raise.
"""
from __future__ import annotations
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

import disposition  # noqa: E402


def _doc(**over):
    base = {
        "doc_id": "drive:f1",
        "source": "drive",
        "path": "/Finance/2024/report.docx",
        "department": "Finance",
        "created_at": "2020-01-01T00:00:00+00:00",
        "source_modified": "2021-06-15T12:00:00+00:00",
    }
    base.update(over)
    return base


# ── path: contains / eq / ne / prefix ─────────────────────────────────────────

def test_path_contains():
    assert disposition.matches(_doc(), [{"field": "path", "op": "contains", "value": "report"}])
    assert not disposition.matches(_doc(), [{"field": "path", "op": "contains", "value": "invoice"}])


def test_path_eq_ne():
    d = _doc(path="/HR/roster.xlsx")
    assert disposition.matches(d, [{"field": "path", "op": "eq", "value": "/HR/roster.xlsx"}])
    assert disposition.matches(d, [{"field": "path", "op": "ne", "value": "/HR/other.xlsx"}])


def test_path_prefix_case_insensitive():
    d = _doc(path="/Finance/2024/report.docx")
    assert disposition.matches(d, [{"field": "path", "op": "prefix", "value": "/Finance/"}])
    # Case-insensitive: rule author's casing need not match the stored path.
    assert disposition.matches(d, [{"field": "path", "op": "prefix", "value": "/finance/"}])
    assert not disposition.matches(d, [{"field": "path", "op": "prefix", "value": "/HR/"}])


def test_prefix_none_value_is_false():
    assert not disposition.matches(_doc(), [{"field": "path", "op": "prefix", "value": None}])


def test_prefix_on_missing_path_is_false():
    d = _doc()
    del d["path"]
    assert not disposition.matches(d, [{"field": "path", "op": "prefix", "value": "/Finance/"}])


# ── parent_folder derivation ──────────────────────────────────────────────────

def test_parent_folder_derived():
    d = _doc(path="/Finance/2024/report.docx")
    assert disposition.matches(d, [{"field": "parent_folder", "op": "eq", "value": "/Finance/2024"}])
    assert disposition.matches(d, [{"field": "parent_folder", "op": "prefix", "value": "/Finance"}])


def test_parent_folder_no_dir():
    # A bare filename has no directory portion.
    assert disposition.matches(_doc(path="report.docx"),
                               [{"field": "parent_folder", "op": "eq", "value": ""}])


def test_parent_folder_missing_path_is_none():
    d = _doc()
    del d["path"]
    # None parent_folder: eq to a string is False, ne is True.
    assert not disposition.matches(d, [{"field": "parent_folder", "op": "eq", "value": "/Finance"}])
    assert disposition.matches(d, [{"field": "parent_folder", "op": "ne", "value": "/Finance"}])


def test_helpers_directly():
    assert disposition._parent_folder("/a/b/c.txt") == "/a/b"
    assert disposition._parent_folder("c.txt") == ""
    assert disposition._parent_folder(None) is None
    assert disposition._parent_folder("") is None


# ── modified_at: before / after with real / None / malformed dates ────────────

def test_modified_at_before():
    d = _doc(source_modified="2021-06-15T12:00:00+00:00")
    assert disposition.matches(d, [{"field": "modified_at", "op": "before", "value": "2024-01-01"}])
    assert not disposition.matches(d, [{"field": "modified_at", "op": "before", "value": "2020-01-01"}])


def test_modified_at_after():
    d = _doc(source_modified="2021-06-15T12:00:00+00:00")
    assert disposition.matches(d, [{"field": "modified_at", "op": "after", "value": "2020-01-01"}])
    assert not disposition.matches(d, [{"field": "modified_at", "op": "after", "value": "2024-01-01"}])


def test_before_after_equal_is_false():
    # Strict comparison: equal dates are neither before nor after.
    d = _doc(source_modified="2024-01-01T00:00:00+00:00")
    assert not disposition.matches(d, [{"field": "modified_at", "op": "before", "value": "2024-01-01T00:00:00+00:00"}])
    assert not disposition.matches(d, [{"field": "modified_at", "op": "after", "value": "2024-01-01T00:00:00+00:00"}])


def test_created_at_before_after_passthrough():
    d = _doc(created_at="2020-01-01T00:00:00+00:00")
    assert disposition.matches(d, [{"field": "created_at", "op": "before", "value": "2021-01-01"}])
    assert disposition.matches(d, [{"field": "created_at", "op": "after", "value": "2019-01-01"}])


def test_modified_at_none_never_matches():
    d = _doc()
    del d["source_modified"]  # column absent — treat as None
    assert not disposition.matches(d, [{"field": "modified_at", "op": "before", "value": "2024-01-01"}])
    assert not disposition.matches(d, [{"field": "modified_at", "op": "after", "value": "2000-01-01"}])


def test_malformed_dates_do_not_raise():
    # Malformed stored value.
    d = _doc(source_modified="not-a-date")
    assert not disposition.matches(d, [{"field": "modified_at", "op": "before", "value": "2024-01-01"}])
    # Malformed rule value.
    d2 = _doc()
    assert not disposition.matches(d2, [{"field": "modified_at", "op": "before", "value": "garbage"}])
    assert not disposition.matches(d2, [{"field": "modified_at", "op": "after", "value": None}])


def test_naive_iso_assumed_utc():
    # A naive timestamp compares against a naive value without raising.
    d = _doc(source_modified="2021-06-15T12:00:00")
    assert disposition.matches(d, [{"field": "modified_at", "op": "before", "value": "2022-01-01"}])


# ── modified_age_days derivation ──────────────────────────────────────────────

def test_modified_age_days_derived():
    forty_days_ago = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
    d = _doc(source_modified=forty_days_ago)
    assert disposition.matches(d, [{"field": "modified_age_days", "op": "gte", "value": 30}])
    assert not disposition.matches(d, [{"field": "modified_age_days", "op": "gte", "value": 90}])


def test_modified_age_days_none_when_column_absent():
    d = _doc()
    del d["source_modified"]
    # None modified_age_days: gt/gte guard against None, so no match.
    assert not disposition.matches(d, [{"field": "modified_age_days", "op": "gt", "value": 0}])


def test_age_days_still_works():
    # Existing created_at-based age_days path is unchanged.
    d = _doc(created_at=(datetime.now(timezone.utc) - timedelta(days=100)).isoformat())
    assert disposition.matches(d, [{"field": "age_days", "op": "gte", "value": 90}])


def test_days_since_helper():
    assert disposition._days_since(None) is None
    assert disposition._days_since("nonsense") is None
    assert disposition._age_days(None) is None
    ninety = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
    assert disposition._days_since(ninety) == 90


# ── validate_match: accept new, reject unknown ────────────────────────────────

@pytest.mark.parametrize("cond", [
    {"field": "path", "op": "prefix", "value": "/Finance/"},
    {"field": "parent_folder", "op": "eq", "value": "/Finance/2024"},
    {"field": "modified_at", "op": "before", "value": "2024-01-01"},
    {"field": "created_at", "op": "after", "value": "2020-01-01"},
    {"field": "modified_age_days", "op": "gte", "value": 90},
])
def test_validate_accepts_new_fields_and_ops(cond):
    disposition.validate_match([cond])  # must not raise


def test_validate_rejects_unknown_field():
    with pytest.raises(ValueError, match="unknown field"):
        disposition.validate_match([{"field": "folder", "op": "eq", "value": "x"}])


def test_validate_rejects_unknown_op():
    with pytest.raises(ValueError, match="unknown op"):
        disposition.validate_match([{"field": "path", "op": "startswith", "value": "x"}])


def test_validate_rejects_malformed_condition():
    with pytest.raises(ValueError, match="malformed condition"):
        disposition.validate_match([{"field": "path"}])
    with pytest.raises(ValueError, match="must be a list"):
        disposition.validate_match({"field": "path", "op": "eq", "value": "x"})


# ── AND-logic across mixed conditions ─────────────────────────────────────────

def test_and_logic_across_mixed_conditions():
    d = _doc(path="/Finance/2024/report.docx", department="Finance",
             source_modified="2021-06-15T12:00:00+00:00")
    rule = [
        {"field": "path", "op": "prefix", "value": "/Finance/"},
        {"field": "modified_at", "op": "before", "value": "2024-01-01"},
        {"field": "department", "op": "eq", "value": "Finance"},
    ]
    assert disposition.matches(d, rule)
    # Any single failing clause fails the whole AND.
    assert not disposition.matches(_doc(path="/HR/x.docx", department="Finance",
                                        source_modified="2021-06-15T12:00:00+00:00"), rule)
    assert not disposition.matches(_doc(path="/Finance/2024/report.docx", department="HR",
                                        source_modified="2021-06-15T12:00:00+00:00"), rule)
    assert not disposition.matches(_doc(path="/Finance/2024/report.docx", department="Finance",
                                        source_modified="2025-06-15T12:00:00+00:00"), rule)


def test_empty_match_matches_everything():
    # Vacuous AND — preserved existing behaviour.
    assert disposition.matches(_doc(), [])
