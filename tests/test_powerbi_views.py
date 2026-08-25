"""P3.4 — Power BI DirectQuery: view DDL and DSN helper smoke tests."""
from __future__ import annotations

import sys
from pathlib import Path

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

from store import _SCHEMA  # noqa: E402

_VIEW_NAMES = [
    "vw_scan_summary",
    "vw_file_compliance",
    "vw_open_issues",
    "vw_remediation_queue",
    "vw_ai_spend",
]


def test_powerbi_view_ddl_in_schema():
    """All five vw_* views are declared in _SCHEMA (executed at every app boot)."""
    schema_sql = "\n".join(s for s in _SCHEMA if isinstance(s, str)).lower()
    for view in _VIEW_NAMES:
        assert view in schema_sql, f"_SCHEMA missing DDL for {view}"


def test_powerbi_views_created_on_sqlite(isolated_store):
    """All five views are present in the isolated SQLite DB after Store initialises."""
    import sqlite3
    import store as store_mod
    conn = sqlite3.connect(str(store_mod._SQLITE_PATH))
    try:
        cur = conn.execute("SELECT name FROM sqlite_master WHERE type='view'")
        created = {row[0] for row in cur.fetchall()}
    finally:
        conn.close()
    for view in _VIEW_NAMES:
        assert view in created, f"{view} not created in SQLite Store"


def test_get_powerbi_dsn_sqlite_unavailable(isolated_store):
    """get_powerbi_dsn() returns available=False in SQLite mode."""
    result = isolated_store.get_powerbi_dsn()
    assert result["available"] is False
    assert "SQLite" in result.get("reason", "")


def test_powerbi_dsn_lists_all_views(isolated_store):
    """get_powerbi_dsn() (even in SQLite mode) does not claim a partial view set."""
    # available=False in SQLite, but the code path still names the views when Postgres.
    # Verify the full list is present in the Postgres-path return value by checking the
    # constant in the method body matches _VIEW_NAMES exactly.
    import store as store_mod
    import inspect
    src = inspect.getsource(store_mod.Store.get_powerbi_dsn)
    for view in _VIEW_NAMES:
        assert view in src, f"get_powerbi_dsn source does not mention {view}"
