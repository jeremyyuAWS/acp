"""disposition.evaluate() — per-condition provenance for rule matching.

Checks that evaluate() returns the same matched/unmatched verdict as matches(),
and that every condition row carries the correct outcome, observed_value, and a
reason string that names the actual vs. expected values — especially when a
missing metadata field was the cause of a mismatch.
"""
from __future__ import annotations
import sys
from pathlib import Path

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
        "size_kb": 100,
    }
    base.update(over)
    return base


def _cond(field, op, value=None):
    c = {"field": field, "op": op}
    if value is not None:
        c["value"] = value
    return c


# ── result shape ──────────────────────────────────────────────────────────────

def test_returns_matched_and_conditions_keys():
    result = disposition.evaluate(_doc(), [_cond("department", "eq", "Finance")])
    assert set(result.keys()) == {"matched", "conditions"}


def test_condition_row_has_required_keys():
    result = disposition.evaluate(_doc(), [_cond("department", "eq", "Finance")])
    row = result["conditions"][0]
    assert set(row.keys()) == {"field", "op", "value", "observed_value", "outcome", "reason"}


def test_empty_match_matches_everything():
    result = disposition.evaluate(_doc(), [])
    assert result["matched"] is True
    assert result["conditions"] == []


# ── matched verdict agrees with matches() ─────────────────────────────────────

def test_matched_true_when_all_conditions_pass():
    match = [_cond("department", "eq", "Finance"),
             _cond("parent_folder", "prefix", "/Finance/")]
    result = disposition.evaluate(_doc(), match)
    assert result["matched"] is True
    assert disposition.matches(_doc(), match) is True


def test_matched_false_when_any_condition_fails():
    match = [_cond("department", "eq", "Finance"),
             _cond("size_kb", "gt", 999)]
    result = disposition.evaluate(_doc(), match)
    assert result["matched"] is False
    assert disposition.matches(_doc(), match) is False


def test_one_row_per_condition():
    match = [_cond("department", "eq", "Finance"),
             _cond("size_kb", "lte", 200),
             _cond("path", "contains", "report")]
    result = disposition.evaluate(_doc(), match)
    assert len(result["conditions"]) == 3


# ── passing conditions ─────────────────────────────────────────────────────────

def test_passing_condition_outcome_and_observed():
    result = disposition.evaluate(_doc(), [_cond("department", "eq", "Finance")])
    row = result["conditions"][0]
    assert row["outcome"] == "pass"
    assert row["observed_value"] == "Finance"
    assert row["value"] == "Finance"


def test_passing_prefix_reason():
    result = disposition.evaluate(_doc(), [_cond("parent_folder", "prefix", "/Finance/")])
    row = result["conditions"][0]
    assert row["outcome"] == "pass"
    assert "starts with" in row["reason"]


def test_passing_gt_reason():
    result = disposition.evaluate(_doc(), [_cond("size_kb", "gt", 50)])
    row = result["conditions"][0]
    assert row["outcome"] == "pass"
    assert "greater than" in row["reason"]


def test_passing_before_reason():
    result = disposition.evaluate(_doc(), [_cond("modified_at", "before", "2022-01-01")])
    row = result["conditions"][0]
    assert row["outcome"] == "pass"
    assert "before" in row["reason"]


# ── failing conditions — field present ─────────────────────────────────────────

def test_failing_condition_outcome_and_observed():
    result = disposition.evaluate(_doc(), [_cond("department", "eq", "Legal")])
    row = result["conditions"][0]
    assert row["outcome"] == "fail"
    assert row["observed_value"] == "Finance"


def test_failing_prefix_reason():
    result = disposition.evaluate(_doc(), [_cond("parent_folder", "prefix", "/Legal/")])
    row = result["conditions"][0]
    assert row["outcome"] == "fail"
    assert "does not start with" in row["reason"]


def test_failing_gt_reason():
    result = disposition.evaluate(_doc(), [_cond("size_kb", "gt", 999)])
    row = result["conditions"][0]
    assert row["outcome"] == "fail"
    assert "not greater than" in row["reason"]


def test_failing_before_reason():
    result = disposition.evaluate(_doc(), [_cond("modified_at", "before", "2020-01-01")])
    row = result["conditions"][0]
    assert row["outcome"] == "fail"
    assert "not before" in row["reason"]


# ── missing metadata — the key explainability case ────────────────────────────

def test_missing_direct_field_fails_and_names_it():
    doc = _doc()
    del doc["department"]
    result = disposition.evaluate(doc, [_cond("department", "eq", "Finance")])
    row = result["conditions"][0]
    assert row["outcome"] == "fail"
    assert row["observed_value"] is None
    assert "'department' not recorded" in row["reason"]


def test_missing_source_modified_fails_modified_age_days():
    doc = _doc()
    del doc["source_modified"]
    result = disposition.evaluate(doc, [_cond("modified_age_days", "gt", 100)])
    row = result["conditions"][0]
    assert row["outcome"] == "fail"
    assert row["observed_value"] is None
    # reason names the source column, not the derived field
    assert "'source_modified' not recorded" in row["reason"]


def test_missing_source_modified_fails_modified_at():
    doc = _doc()
    del doc["source_modified"]
    result = disposition.evaluate(doc, [_cond("modified_at", "before", "2025-01-01")])
    row = result["conditions"][0]
    assert row["outcome"] == "fail"
    assert row["observed_value"] is None
    assert "'source_modified' not recorded" in row["reason"]


def test_missing_created_at_fails_age_days():
    doc = _doc()
    del doc["created_at"]
    result = disposition.evaluate(doc, [_cond("age_days", "gt", 30)])
    row = result["conditions"][0]
    assert row["outcome"] == "fail"
    assert row["observed_value"] is None
    assert "'created_at' not recorded" in row["reason"]


def test_missing_path_fails_parent_folder():
    doc = _doc()
    del doc["path"]
    result = disposition.evaluate(doc, [_cond("parent_folder", "prefix", "/Finance/")])
    row = result["conditions"][0]
    assert row["outcome"] == "fail"
    assert row["observed_value"] is None
    assert "'path' not recorded" in row["reason"]


def test_missing_field_ne_still_passes():
    # ne with a missing field passes (None != "Finance") — this is the expected behaviour
    # from matches(); evaluate must agree and explain it.
    doc = _doc()
    del doc["department"]
    result = disposition.evaluate(doc, [_cond("department", "ne", "Finance")])
    row = result["conditions"][0]
    assert row["outcome"] == "pass"
    assert row["observed_value"] is None
    assert "not equal" in row["reason"]


def test_missing_field_prefix_fails_with_empty_string_explanation():
    # prefix and contains treat None as "" — so a non-empty expected always fails.
    # The reason should mention both the absence and how it was treated.
    doc = _doc()
    del doc["path"]
    result = disposition.evaluate(doc, [_cond("path", "prefix", "/Finance/")])
    row = result["conditions"][0]
    assert row["outcome"] == "fail"
    assert "empty string" in row["reason"]


# ── observed_value reflects derived values, not raw doc fields ────────────────

def test_observed_value_for_parent_folder_is_derived():
    result = disposition.evaluate(_doc(), [_cond("parent_folder", "eq", "/Finance/2024")])
    row = result["conditions"][0]
    assert row["observed_value"] == "/Finance/2024"  # derived from path


def test_observed_value_for_modified_at_is_source_modified():
    doc = _doc(source_modified="2021-06-15T12:00:00+00:00")
    result = disposition.evaluate(doc, [_cond("modified_at", "before", "2025-01-01")])
    row = result["conditions"][0]
    assert row["observed_value"] == "2021-06-15T12:00:00+00:00"
