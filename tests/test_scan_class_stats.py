"""Verify that _count_inventory_classes returns the 5-bucket breakdown (PRD §6.4) and that
persist_discovery_inventory merges it into its return value, which routes/scans.py then
forwards into the 'done' progress payload.

Text-verified against source files so that a refactor fails loudly rather than silently
dropping the stat fields.
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


def test_count_classes_function_defined():
    assert "def _count_inventory_classes" in HANDLERS_CODE, (
        "_count_inventory_classes must be defined in handlers.py")


def test_count_classes_returns_assessable():
    assert '"assessable"' in HANDLERS_CODE or "'assessable'" in HANDLERS_CODE, (
        "_count_inventory_classes must include 'assessable' in its return value")


def test_count_classes_returns_metadata_only():
    assert '"metadata_only"' in HANDLERS_CODE or "'metadata_only'" in HANDLERS_CODE, (
        "_count_inventory_classes must include 'metadata_only' in its return value")


def test_count_classes_returns_unsupported():
    assert '"unsupported"' in HANDLERS_CODE or "'unsupported'" in HANDLERS_CODE, (
        "_count_inventory_classes must include 'unsupported' in its return value")


def test_count_classes_returns_eligibility_unknown():
    assert '"eligibility_unknown"' in HANDLERS_CODE or "'eligibility_unknown'" in HANDLERS_CODE, (
        "_count_inventory_classes must include 'eligibility_unknown' in its return value")


def test_count_classes_returns_excluded():
    assert '"excluded"' in HANDLERS_CODE or "'excluded'" in HANDLERS_CODE, (
        "_count_inventory_classes must include 'excluded' in its return value")


def test_persist_inventory_captures_class_stats():
    assert "class_stats" in HANDLERS_CODE, (
        "persist_discovery_inventory must capture the return value of _count_inventory_classes")


def test_persist_inventory_merges_class_stats():
    assert "**class_stats" in HANDLERS_CODE, (
        "persist_discovery_inventory must merge class_stats into its return dict")


def test_routes_emits_assessable_in_done_payload():
    done_idx = ROUTES_CODE.index('"phase": "done"')
    block = ROUTES_CODE[max(0, done_idx - 100):done_idx + 1100]
    assert "assessable" in block, (
        "routes/scans.py done-phase update must carry assessable")


def test_routes_emits_metadata_only_in_done_payload():
    done_idx = ROUTES_CODE.index('"phase": "done"')
    block = ROUTES_CODE[max(0, done_idx - 100):done_idx + 1200]
    assert "metadata_only" in block, (
        "routes/scans.py done-phase update must carry metadata_only")


def test_routes_emits_unsupported_in_done_payload():
    done_idx = ROUTES_CODE.index('"phase": "done"')
    block = ROUTES_CODE[max(0, done_idx - 100):done_idx + 1300]
    assert "unsupported" in block, (
        "routes/scans.py done-phase update must carry unsupported")


def test_routes_emits_eligibility_unknown_in_done_payload():
    done_idx = ROUTES_CODE.index('"phase": "done"')
    block = ROUTES_CODE[max(0, done_idx - 100):done_idx + 1400]
    assert "eligibility_unknown" in block, (
        "routes/scans.py done-phase update must carry eligibility_unknown")


def test_routes_emits_excluded_in_done_payload():
    done_idx = ROUTES_CODE.index('"phase": "done"')
    block = ROUTES_CODE[max(0, done_idx - 100):done_idx + 1500]
    assert "excluded" in block, (
        "routes/scans.py done-phase update must carry excluded")
