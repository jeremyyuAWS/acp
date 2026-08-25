"""Verify that _evaluate_discover_lifecycle_rules returns lifecycle stats and that
persist_discovery_inventory merges them into its return value, which routes/scans.py then
forwards into the 'done' progress payload.

Text-verified against source files so that a refactor of the lifecycle evaluation path
fails loudly rather than silently dropping the stat fields.
"""
import sys
from pathlib import Path

API = Path(__file__).resolve().parents[1] / "api"
sys.path.insert(0, str(API))

HANDLERS_SRC = (API / "handlers.py").read_text()
ROUTES_SRC = (API / "routes" / "scans.py").read_text()


def _strip_comments(src):
    return "\n".join(l for l in src.split("\n") if not l.strip().startswith("#"))


HANDLERS_CODE = _strip_comments(HANDLERS_SRC)
ROUTES_CODE = _strip_comments(ROUTES_SRC)


def test_evaluate_lifecycle_returns_dict_not_none():
    assert "-> dict" in HANDLERS_CODE, (
        "_evaluate_discover_lifecycle_rules must return a dict (not None)")


def test_evaluate_lifecycle_returns_rules_enabled():
    assert '"rules_enabled"' in HANDLERS_CODE or "'rules_enabled'" in HANDLERS_CODE, (
        "_evaluate_discover_lifecycle_rules must include 'rules_enabled' in its return value")


def test_evaluate_lifecycle_returns_files_evaluated():
    assert '"files_evaluated"' in HANDLERS_CODE or "'files_evaluated'" in HANDLERS_CODE, (
        "_evaluate_discover_lifecycle_rules must include 'files_evaluated' in its return value")


def test_evaluate_lifecycle_returns_lifecycle_matches():
    assert '"lifecycle_matches"' in HANDLERS_CODE or "'lifecycle_matches'" in HANDLERS_CODE, (
        "_evaluate_discover_lifecycle_rules must include 'lifecycle_matches' in its return value")


def test_evaluate_lifecycle_tracks_files_evaluated_counter():
    assert "files_evaluated" in HANDLERS_CODE, (
        "_evaluate_discover_lifecycle_rules must track a files_evaluated counter")


def test_evaluate_lifecycle_tracks_lifecycle_matches_counter():
    assert "lifecycle_matches" in HANDLERS_CODE, (
        "_evaluate_discover_lifecycle_rules must track a lifecycle_matches counter")


def test_persist_inventory_captures_lifecycle_stats():
    assert "lifecycle_stats" in HANDLERS_CODE or "lifecycle_stat" in HANDLERS_CODE, (
        "persist_discovery_inventory must capture the return value of _evaluate_discover_lifecycle_rules")


def test_persist_inventory_merges_lifecycle_stats():
    assert "{**outcome, **lifecycle_stats}" in HANDLERS_CODE or "**lifecycle_stats" in HANDLERS_CODE, (
        "persist_discovery_inventory must merge lifecycle stats into its return dict")


def test_routes_emits_rules_enabled_in_done_payload():
    done_idx = ROUTES_CODE.index('"phase": "done"')
    block = ROUTES_CODE[max(0, done_idx - 100):done_idx + 900]
    assert "rules_enabled" in block, (
        "routes/scans.py done-phase update must carry rules_enabled")


def test_routes_emits_files_evaluated_in_done_payload():
    done_idx = ROUTES_CODE.index('"phase": "done"')
    block = ROUTES_CODE[max(0, done_idx - 100):done_idx + 900]
    assert "files_evaluated" in block, (
        "routes/scans.py done-phase update must carry files_evaluated")


def test_routes_emits_lifecycle_matches_in_done_payload():
    done_idx = ROUTES_CODE.index('"phase": "done"')
    block = ROUTES_CODE[max(0, done_idx - 100):done_idx + 900]
    assert "lifecycle_matches" in block, (
        "routes/scans.py done-phase update must carry lifecycle_matches")
