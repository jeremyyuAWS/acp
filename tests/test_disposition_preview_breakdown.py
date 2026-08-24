"""_preview() breakdown — effective, superseded, exempted, unable_to_evaluate.

Tests the _preview() helper in api/routes/disposition.py directly (not via HTTP),
monkeypatching core.store so no database is needed.
"""
from __future__ import annotations
import sys
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

# Minimal stubs so imports succeed without a real DB or web framework.
core_stub = MagicMock()
sys.modules.setdefault("core", core_stub)
for _mod in (
    "fastapi", "fastapi.responses", "fastapi.routing",
    "pydantic",
    "routes", "routes.system",
):
    sys.modules.setdefault(_mod, MagicMock())

import importlib.util  # noqa: E402
import disposition  # noqa: E402

# Load routes/disposition.py directly to bypass routes/__init__ (which pulls
# in all sibling routes and their fastapi/DB dependencies).
_spec = importlib.util.spec_from_file_location(
    "routes.disposition", ACP / "api/routes/disposition.py",
    submodule_search_locations=[str(ACP / "api/routes")],
)
rdis = importlib.util.module_from_spec(_spec)
sys.modules["routes.disposition"] = rdis
_spec.loader.exec_module(rdis)


def _pol(policy_id, action, match, ordinal=1, enabled=True):
    return {
        "policy_id": policy_id,
        "action": action,
        "match": json.dumps(match),
        "enabled": 1 if enabled else 0,
        "ordinal": ordinal,
        "requires_approval": True,
        "name": policy_id,
        "action_config": "{}",
    }


def _doc(**kwargs):
    base = {
        "doc_id": "drive:f1",
        "source": "drive",
        "path": "/Finance/2024/report.docx",
        "department": "Finance",
        "created_at": "2020-01-01T00:00:00+00:00",
        "source_modified": "2021-06-15T12:00:00+00:00",
        "size_kb": 100,
    }
    base.update(kwargs)
    return base


MATCH_FINANCE = [{"field": "department", "op": "eq", "value": "Finance"}]
MATCH_LARGE = [{"field": "size_kb", "op": "gt", "value": 999}]


def _run(match, action, policy_id, docs, policies):
    """Call _preview with mocked store."""
    with patch.object(rdis.core.store, "list_all_documents", return_value=docs), \
         patch.object(rdis.core.store, "list_pending_disposition_candidates", return_value=[]), \
         patch.object(rdis.core.store, "list_disposition_policies", return_value=policies):
        return rdis._preview(match, action, policy_id, "owner@x.com")


# ── result shape ──────────────────────────────────────────────────────────────

def test_preview_returns_breakdown_keys():
    r = _run(MATCH_FINANCE, "archive", "p1", [_doc()], [_pol("p1", "archive", MATCH_FINANCE)])
    assert {"effective", "superseded", "exempted", "unable_to_evaluate"} <= set(r.keys())


def test_would_match_unchanged():
    r = _run(MATCH_FINANCE, "archive", "p1", [_doc()], [_pol("p1", "archive", MATCH_FINANCE)])
    assert r["would_match"] == 1
    assert r["effective"] == 1
    assert r["superseded"] == 0


# ── effective — the only matching rule ───────────────────────────────────────

def test_all_effective_when_no_competing_rules():
    docs = [_doc(doc_id="d1"), _doc(doc_id="d2")]
    r = _run(MATCH_FINANCE, "archive", "p1", docs, [_pol("p1", "archive", MATCH_FINANCE)])
    assert r["effective"] == 2
    assert r["superseded"] == 0


def test_tag_rule_all_effective_no_superseded():
    # Tag rules never compete with archive/delete — all matches are effective.
    r = _run(MATCH_FINANCE, "tag", "p1", [_doc()], [_pol("p1", "tag", MATCH_FINANCE)])
    assert r["effective"] == 1
    assert r["superseded"] == 0


# ── superseded — another rule wins ────────────────────────────────────────────

def test_archive_superseded_by_higher_priority_archive():
    # p1 (ordinal=1, archive) and p2 (ordinal=2, archive) both match.
    # p1 is higher priority — p2 is superseded.
    doc = _doc()
    policies = [
        _pol("p1", "archive", MATCH_FINANCE, ordinal=1),
        _pol("p2", "archive", MATCH_FINANCE, ordinal=2),
    ]
    r = _run(MATCH_FINANCE, "archive", "p2", [doc], policies)
    assert r["superseded"] == 1
    assert r["effective"] == 0
    assert r["would_match"] == 1


def test_higher_priority_rule_is_effective():
    doc = _doc()
    policies = [
        _pol("p1", "archive", MATCH_FINANCE, ordinal=1),
        _pol("p2", "archive", MATCH_FINANCE, ordinal=2),
    ]
    r = _run(MATCH_FINANCE, "archive", "p1", [doc], policies)
    assert r["effective"] == 1
    assert r["superseded"] == 0


def test_no_superseded_when_competing_rule_does_not_match():
    # p2 matches a different condition — p1 is fully effective.
    doc = _doc()
    policies = [
        _pol("p1", "archive", MATCH_FINANCE, ordinal=1),
        _pol("p2", "archive", MATCH_LARGE, ordinal=2),
    ]
    r = _run(MATCH_FINANCE, "archive", "p1", [doc], policies)
    assert r["effective"] == 1
    assert r["superseded"] == 0


def test_superseded_draft_always_zero():
    # Draft rules (policy_id=None) have no rank — superseded is always 0.
    doc = _doc()
    policies = [_pol("p1", "archive", MATCH_FINANCE, ordinal=1)]
    r = _run(MATCH_FINANCE, "archive", None, [doc], policies)
    assert r["superseded"] == 0
    assert r["effective"] == 1


# ── exempted ─────────────────────────────────────────────────────────────────

def test_exempted_doc_not_in_would_match():
    doc = _doc(lifecycle_status="Exempted")
    r = _run(MATCH_FINANCE, "archive", "p1", [doc], [_pol("p1", "archive", MATCH_FINANCE)])
    assert r["would_match"] == 0
    assert r["exempted"] == 1
    assert r["effective"] == 0


def test_non_exempted_doc_not_counted_in_exempted():
    doc = _doc()
    r = _run(MATCH_FINANCE, "archive", "p1", [doc], [_pol("p1", "archive", MATCH_FINANCE)])
    assert r["exempted"] == 0
    assert r["effective"] == 1


def test_exempted_doc_that_doesnt_match_not_counted():
    # Exempted doc that also doesn't satisfy the conditions.
    doc = _doc(department="Legal", lifecycle_status="Exempted")
    r = _run(MATCH_FINANCE, "archive", "p1", [doc], [_pol("p1", "archive", MATCH_FINANCE)])
    assert r["exempted"] == 0
    assert r["would_match"] == 0


# ── unable_to_evaluate ───────────────────────────────────────────────────────

def test_missing_field_counted_as_unable_to_evaluate():
    doc = _doc()
    del doc["department"]
    r = _run(MATCH_FINANCE, "archive", "p1", [doc], [_pol("p1", "archive", MATCH_FINANCE)])
    assert r["would_match"] == 0
    assert r["unable_to_evaluate"] == 1
    assert r["effective"] == 0


def test_ne_missing_field_passes_not_unable():
    # None != "Finance" is True — ne with a missing field passes, so it IS in would_match.
    match = [{"field": "department", "op": "ne", "value": "Finance"}]
    doc = _doc()
    del doc["department"]
    r = _run(match, "archive", "p1", [doc], [_pol("p1", "archive", match)])
    assert r["would_match"] == 1
    assert r["unable_to_evaluate"] == 0
    assert r["effective"] == 1


def test_no_conditions_no_unable():
    # Empty match matches everything — no missing-metadata uncertainty.
    r = _run([], "archive", "p1", [_doc()], [_pol("p1", "archive", [])])
    assert r["would_match"] == 1
    assert r["unable_to_evaluate"] == 0


def test_genuinely_non_matching_not_counted_as_unable():
    # doc.size_kb=100, condition gt 999 — fails because value is present and small, not absent.
    match = [{"field": "size_kb", "op": "gt", "value": 999}]
    r = _run(match, "archive", "p1", [_doc()], [_pol("p1", "archive", match)])
    assert r["would_match"] == 0
    assert r["unable_to_evaluate"] == 0


# ── mixed scenarios ───────────────────────────────────────────────────────────

def test_mixed_effective_superseded_unable():
    match = MATCH_FINANCE
    doc_effective = _doc(doc_id="d1")
    doc_missing = _doc(doc_id="d2")
    del doc_missing["department"]
    doc_superseded = _doc(doc_id="d3")
    policies = [
        _pol("p1", "archive", match, ordinal=1),
        _pol("p2", "archive", match, ordinal=2),
    ]
    r = _run(match, "archive", "p2", [doc_effective, doc_missing, doc_superseded], policies)
    assert r["would_match"] == 2   # d1 and d3 matched (d2 missing dept)
    assert r["unable_to_evaluate"] == 1  # d2
    assert r["superseded"] == 2   # both d1 and d3 overridden by p1
    assert r["effective"] == 0


# ── unable_to_evaluate_fields ─────────────────────────────────────────────────

def test_unable_fields_names_the_missing_field():
    doc = _doc()
    del doc["department"]
    r = _run(MATCH_FINANCE, "archive", "p1", [doc], [_pol("p1", "archive", MATCH_FINANCE)])
    assert r["unable_to_evaluate_fields"] == {"department": 1}


def test_unable_fields_empty_when_no_unable():
    r = _run(MATCH_FINANCE, "archive", "p1", [_doc()], [_pol("p1", "archive", MATCH_FINANCE)])
    assert r["unable_to_evaluate_fields"] == {}


def test_unable_fields_counts_multiple_docs_missing_same_field():
    doc1 = _doc(doc_id="d1")
    del doc1["department"]
    doc2 = _doc(doc_id="d2")
    del doc2["department"]
    r = _run(MATCH_FINANCE, "archive", "p1", [doc1, doc2], [_pol("p1", "archive", MATCH_FINANCE)])
    assert r["unable_to_evaluate"] == 2
    assert r["unable_to_evaluate_fields"] == {"department": 2}


def test_unable_fields_tracks_each_missing_field_per_doc():
    # Two conditions; one doc missing both fields, another missing only one.
    match = [
        {"field": "department", "op": "eq", "value": "Finance"},
        {"field": "size_kb", "op": "gt", "value": 999},
    ]
    doc_both_missing = _doc(doc_id="d1")
    del doc_both_missing["department"]
    del doc_both_missing["size_kb"]
    doc_dept_missing = _doc(doc_id="d2", size_kb=100)  # size_kb present but fails; dept missing
    del doc_dept_missing["department"]
    r = _run(match, "archive", "p1", [doc_both_missing, doc_dept_missing],
             [_pol("p1", "archive", match)])
    # Both docs are unable_to_evaluate (both have at least one missing field)
    assert r["unable_to_evaluate"] == 2
    # department missing in both; size_kb missing only in d1
    assert r["unable_to_evaluate_fields"]["department"] == 2
    assert r["unable_to_evaluate_fields"]["size_kb"] == 1


def test_unable_fields_not_in_result_shape_test():
    # Confirms the key is always present in the response (even when empty).
    r = _run([], "archive", "p1", [_doc()], [_pol("p1", "archive", [])])
    assert "unable_to_evaluate_fields" in r
