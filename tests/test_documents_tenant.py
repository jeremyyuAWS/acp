"""`documents` gets its own tenant column, separate from the document's business owner.

WHAT WAS ACTUALLY WRONG. Not that the tenant was missing — it was there, written into `owner`,
the column ADR 0003 defines as the document's BUSINESS owner and sits beside `department`,
`business_criticality` and `regulatory_tags`. save_scan passes the same report["owner"] it writes
to scan_runs.owner_email; handlers passes payload["user"].

So the two meanings were collapsed into one column, and that is worse than an absence: it works
until somebody populates `owner` as designed, at which point every tenant-scoped read silently
starts matching on a person's name. Nothing errors. The estate becomes visible to the wrong
customer.

`documents` is also the only table carrying `department`, which is exactly where a "filter the
estate by department" view would be built — so this is the column that view has to scope on.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))

SRC = (ROOT / "api" / "store.py").read_text()
HANDLERS = (ROOT / "api" / "handlers.py").read_text()


def test_the_column_exists():
    assert "ALTER TABLE documents ADD COLUMN IF NOT EXISTS owner_email TEXT" in SRC


def test_both_writers_populate_it():
    """A column nobody writes is worse than no column: a scoped read on it returns nothing, which
    looks like an empty estate rather than a bug."""
    assert re.search(r"owner_email=report\.get\(\"owner\"\)", SRC), "save_scan does not pass it"
    assert re.search(r"owner=user, owner_email=user", HANDLERS), "the handler does not pass it"


def test_the_insert_and_the_conflict_both_carry_it():
    """ON CONFLICT matters as much as INSERT here. `owner` is NOT updated on conflict, so a
    document keeps whoever scanned it FIRST — for a tenant id that pins visibility to the wrong
    customer forever once two tenants share a doc_id."""
    ins = re.search(r"INSERT INTO documents\((.*?)\)", SRC, re.S)
    assert ins and "owner_email" in ins.group(1), "owner_email missing from the INSERT column list"
    conflict = SRC[SRC.index("ON CONFLICT(doc_id)"):SRC.index("ON CONFLICT(doc_id)") + 900]
    assert "owner_email=EXCLUDED.owner_email" in conflict, "conflict path drops the tenant"


def test_the_placeholder_count_matches_the_columns():
    """A mismatch here is not a subtle failure — it is a runtime error on every scan — but it is
    also exactly the kind of thing that slips in when a column is added to a long literal."""
    ins = re.search(r"INSERT INTO documents\((.*?)\) \"\s*\n\s*\"VALUES\((.*?)\)", SRC, re.S)
    assert ins, "could not locate the documents INSERT"
    cols = [c for c in re.split(r"[,\s\"]+", ins.group(1)) if c]
    placeholders = ins.group(2).count("%s")
    assert len(cols) == placeholders, f"{len(cols)} columns vs {placeholders} placeholders"


def test_the_backfill_rides_the_existing_switch():
    """Same ACP_LEGACY_SCAN_OWNER that backfills scan_runs. Two switches is how the two tables
    end up disagreeing about who owns the same scan's documents."""
    assert "UPDATE documents SET owner_email=" in SRC
    legacy = SRC[SRC.index("_LEGACY_OWNER = os.environ"):]
    assert legacy.index("UPDATE scan_runs SET owner_email") < legacy.index("UPDATE documents SET owner_email")
    # Guarded by the same validation, so a malformed value cannot reach the DDL string.
    assert 'all(c.isalnum() or c in ".+-_@" for c in _LEGACY_OWNER)' in SRC


def test_null_is_not_treated_as_a_wildcard_anywhere_yet():
    """No scoped read exists yet — this pins that when one is written, it is written against
    owner_email and not against `owner`. If this starts failing because a query appeared, the
    right response is to check that query excludes NULL, not to delete this test."""
    assert "WHERE owner_email IS NULL" in SRC          # the backfill, and only the backfill
    assert SRC.count("FROM documents WHERE owner=") == 0, (
        "a query scopes documents on `owner` — that is the business-owner column, and it will "
        "stop meaning 'tenant' the moment ADR 0003's intent is implemented")


def test_owner_is_still_written_so_nothing_changes_today():
    """The migration is additive on purpose. `owner` keeps receiving exactly what it did, so this
    change cannot alter any existing behaviour — only make the next one safe."""
    assert re.search(r"owner=report\.get\(\"owner\"\),\s*\n\s*owner_email=report\.get\(\"owner\"\)", SRC)
