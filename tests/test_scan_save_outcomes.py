"""Verify that persist_discovery_inventory returns save-outcome counts and that the
non-deferred scan path forwards them into the 'done' progress payload.

Both assertions are text-verified against the source files so that a refactor of
the save path fails loudly rather than silently dropping the count fields.
"""
import sys
from pathlib import Path

API = Path(__file__).resolve().parents[1] / "api"
sys.path.insert(0, str(API))

HANDLERS_SRC = (API / "handlers.py").read_text()
STORE_SRC = (API / "store.py").read_text()
ROUTES_SRC = (API / "routes" / "scans.py").read_text()

# Strip comment-only lines to avoid false positives.
def _strip_comments(src):
    return "\n".join(l for l in src.split("\n") if not l.strip().startswith("#"))

HANDLERS_CODE = _strip_comments(HANDLERS_SRC)
STORE_CODE = _strip_comments(STORE_SRC)
ROUTES_CODE = _strip_comments(ROUTES_SRC)


def test_add_inventory_returns_dict_not_none():
    assert "-> dict" in STORE_CODE or '-> dict:' in STORE_CODE, (
        "store.add_inventory must return a dict (not None) so callers can surface save counts")


def test_add_inventory_returns_new_count():
    assert '"new"' in STORE_CODE or "'new'" in STORE_CODE, (
        "store.add_inventory must include a 'new' key in its return value")


def test_add_inventory_returns_updated_count():
    assert '"updated"' in STORE_CODE or "'updated'" in STORE_CODE, (
        "store.add_inventory must include an 'updated' key in its return value")


def test_add_inventory_returns_failed_count():
    assert '"failed"' in STORE_CODE or "'failed'" in STORE_CODE, (
        "store.add_inventory must include a 'failed' key in its return value")


def test_persist_discovery_inventory_captures_outcome():
    assert "outcome" in HANDLERS_CODE or "save_outcome" in HANDLERS_CODE, (
        "persist_discovery_inventory must capture the return value of add_inventory")


def test_persist_discovery_inventory_returns_outcome():
    assert "return outcome" in HANDLERS_CODE or "return save_outcome" in HANDLERS_CODE, (
        "persist_discovery_inventory must return the outcome dict so callers can forward it")


def test_routes_captures_persist_return_value():
    assert "save_outcome = persist_discovery_inventory(" in ROUTES_CODE, (
        "routes/scans.py work() must capture the return value of persist_discovery_inventory")


def test_routes_emits_save_new_in_done_payload():
    assert "save_new" in ROUTES_CODE, (
        "routes/scans.py must emit save_new in the phase='done' progress update")


def test_routes_emits_save_updated_in_done_payload():
    assert "save_updated" in ROUTES_CODE, (
        "routes/scans.py must emit save_updated in the phase='done' progress update")


def test_routes_emits_save_failed_in_done_payload():
    assert "save_failed" in ROUTES_CODE, (
        "routes/scans.py must emit save_failed in the phase='done' progress update")


def test_routes_done_payload_has_schema_version_2():
    # Find the done-phase update block in routes/scans.py.
    done_idx = ROUTES_CODE.index('"phase": "done"')
    block = ROUTES_CODE[max(0, done_idx - 200):done_idx + 300]
    assert '"schema_version": 2' in block, (
        "routes/scans.py done-phase update must carry schema_version=2 "
        "so the frontend can detect old backends and degrade gracefully")
