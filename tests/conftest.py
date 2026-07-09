"""Shared test config.

Point run_scan("local") at the frozen oracle corpus (test-corpus/oracle/) instead
of test-corpus/files/ — the demo estate in files/ changes with the demo's needs
(it became the 100-file legal corpus in f442a08, silently breaking every filename
the scan regression suite asserts on), while oracle/ is the fixed set of synthetic
rule-trigger documents the assertions were written against. Regenerate them with
scripts/generate_test_corpus.py.
"""
import os
import sys
import tempfile
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
os.environ.setdefault("ACP_LOCAL_CORPUS", str(ACP / "test-corpus/oracle"))
sys.path.insert(0, str(ACP / "api"))

# Columns that exist ONLY as ALTER statements in store._SCHEMA. tests/test_hitl_deferral.py's
# fixture strips every ALTER out of that shared module-level list *in place*, so any Store
# built after it runs is missing them. Re-add defensively so DB-backed tests stay
# order-independent (same posture as tests/test_remediate_review_publish.py's fixture).
_MIGRATION_DDL = (
    "ALTER TABLE hitl_queue ADD COLUMN approved_value TEXT",
    "ALTER TABLE hitl_queue ADD COLUMN proposals TEXT",
    "ALTER TABLE hitl_queue ADD COLUMN validated INT",
)


@pytest.fixture()
def isolated_store():
    """A Store backed by its own temp SQLite file.

    store._SQLITE_PATH is hardcoded to <repo>/acp.db — there is no env var for it — so a test
    that just constructs Store() silently shares one on-disk database with every other test
    (and with the developer's real data). Point the module at a temp file instead. Never
    reload the store module to achieve this: reload swaps the module object out from under
    anything that did `from store import ...`.
    """
    import store as store_mod
    store_mod._SQLITE_PATH = Path(tempfile.mkdtemp()) / "acp-test.db"
    st = store_mod.Store()
    for ddl in _MIGRATION_DDL:
        with st._db.cursor() as cur:
            try:
                st._db.execute(cur, ddl)
            except Exception:
                pass   # already present
    return st
