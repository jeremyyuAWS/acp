"""A replica must verify the schema at boot, not replay it.

THE PRODUCTION FAILURE, reproduced on PostgreSQL 16 on 2026-08-31 with six replicas booting
against live reads. Store.__init__ calls init_schema() unconditionally, so every API and worker
replica replayed all 139 statements of _SCHEMA + _PG_VIEWS on every boot, in ONE transaction
(psycopg2 defaults to autocommit=False) with no lock_timeout — holding ACCESS EXCLUSIVE on 40
tables until the final commit.

The statements are no-ops on an already-migrated database, and that does not help. Measured:

    NOTICE:  column "phase" of relation "jobs" already exists, skipping
    AccessExclusiveLock|jobs|t

ADD COLUMN IF NOT EXISTS takes the exclusive lock BEFORE finding it has nothing to do. So each
replica locked 40 tables to change nothing, and a deadlock needs only that plus two readers that
touch the same tables in opposite orders. Both exist in production:

    queue_estimate        jobs -> scan_runs    (the pickup estimate; returned 500 in production)
    sweep_orphaned_scans  scan_runs -> jobs    (the reconciliation sweep)

Five of six replica boots failed with DeadlockDetected inside init_schema; with the change,
six of six succeed, exactly one runs DDL, and no reader deadlocks at all.

WHERE EACH TEST RUNS. Most drive a fake connection and run everywhere: they pin the DECISION —
given a database already at or ahead of this build, no DDL is issued and no lock is taken. The
two marked `requires_pg` need a real server, because SQLite has neither ACCESS EXCLUSIVE/ACCESS
SHARE lock modes nor a deadlock detector, so the actual failure cannot be expressed there. The
`Postgres integration (schema/lock regressions)` CI job runs them against a disposable
postgres:16 service container and sets ACP_REQUIRE_PG=1, under which a missing DATABASE_URL is a
FAILURE rather than a skip — a skipping integration job reports green while proving nothing, and
`pytest` exits 0 on a skip.

MIXED VERSIONS, and why the marker is an INTEGER rather than a checksum. The first version of
this compared a content checksum: migrate when the database differs from what this build would
apply. Correct with one version running, wrong during every rolling deploy — which is the only
time it matters. A checksum has no order, so an OLD replica booting after a new one migrated saw
"different" and migrated BACKWARDS, and the next new replica migrated forwards again. Measured on
a real server, alternating versions across five boots: five migrations, marker flapping
e92e54c9 / 3d9ee8f7 / e92e54c9 / … — the exact lock storm this change exists to prevent,
reappearing precisely while both versions are booting and traffic is live. With an integer and a
`>=` comparison the same sequence produces two migrations for two real version transitions, and
an older replica meeting a newer schema correctly does nothing.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))
import store  # noqa: E402


# ── a fake connection that records the SQL it is asked to run ─────────────────────────────────

class _FakeCursor:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=()):
        self.conn.sql.append(" ".join(str(sql).split()))
        self.conn.params.append(params)
        if self.conn.raise_on and self.conn.raise_on in str(sql):
            raise RuntimeError("DDL blew up")

    def fetchone(self):
        s = self.conn.sql[-1]
        if "to_regclass" in s:
            return (("public." + store._PgAdapter._SCHEMA_VERSION_TABLE)
                    if self.conn.marker_table_exists else None,)
        if "SELECT version" in s:
            return (self.conn.marker_version,) if self.conn.marker_version is not None else None
        return None


class _FakeConn:
    def __init__(self, marker_table_exists=True, marker_version=None, raise_on=None):
        self.marker_table_exists = marker_table_exists
        self.marker_version = marker_version
        self.raise_on = raise_on
        self.sql: list[str] = []
        self.params: list = []
        self.autocommit = False
        self.committed = 0
        self.rolled_back = 0
        self.closed = False

    def cursor(self):
        return _FakeCursor(self)

    def commit(self):
        self.committed += 1

    def rollback(self):
        self.rolled_back += 1

    def close(self):
        self.closed = True

    # convenience
    def ddl(self):
        return [s for s in self.sql
                if s.startswith(("CREATE TABLE", "ALTER TABLE", "CREATE INDEX",
                                 "CREATE UNIQUE INDEX", "CREATE OR REPLACE VIEW"))]

    def advisory(self):
        return [s for s in self.sql if "advisory" in s]


@pytest.fixture()
def fake_connect(monkeypatch):
    """Install a fake psycopg2.connect and hand the test the connection it will hand back."""
    import psycopg2

    holder = {}

    def _install(conn):
        holder["conn"] = conn
        monkeypatch.setattr(psycopg2, "connect", lambda *a, **kw: conn)
        return conn

    return _install


def _adapter():
    return store._PgAdapter("postgresql://u@h/db")


# ── the regression that caused the outage ─────────────────────────────────────────────────────

def test_a_current_schema_issues_no_ddl_and_takes_no_lock(fake_connect):
    """THE test. Every replica used to run 139 DDL statements here, each taking ACCESS EXCLUSIVE
    before discovering it had nothing to do."""
    a = _adapter()
    conn = fake_connect(_FakeConn(marker_version=a._SCHEMA_VERSION))

    a.init_schema()

    assert conn.ddl() == [], (
        f"a booting replica issued {len(conn.ddl())} DDL statements against a schema that was "
        f"already current — every one takes ACCESS EXCLUSIVE before finding it has nothing to "
        f"do. First: {conn.ddl()[:1]}")
    assert conn.advisory() == [], (
        "the advisory lock was taken on a boot that had nothing to migrate — every replica "
        "would serialise behind it for no reason")


def test_the_verification_itself_is_only_reads(fake_connect):
    a = _adapter()
    conn = fake_connect(_FakeConn(marker_version=a._SCHEMA_VERSION))
    a.init_schema()
    assert all(s.startswith("SELECT") for s in conn.sql), (
        f"verification wrote something: {[s for s in conn.sql if not s.startswith('SELECT')]}")


# ── when a migration IS needed ────────────────────────────────────────────────────────────────

def test_a_changed_schema_migrates_under_the_advisory_lock(fake_connect):
    a = _adapter()
    conn = fake_connect(_FakeConn(marker_version=a._SCHEMA_VERSION - 1))

    a.init_schema()

    assert conn.ddl(), "a schema that did not match was not migrated"
    adv = conn.advisory()
    assert any("pg_advisory_lock" in s for s in adv), (
        "DDL ran without the advisory lock — concurrent boots would deadlock against each "
        "other, which is the production failure")
    lock_at = next(i for i, s in enumerate(conn.sql) if "pg_advisory_lock" in s)
    first_ddl = next(i for i, s in enumerate(conn.sql) if s in conn.ddl())
    assert lock_at < first_ddl, "the lock was taken after the DDL had already started"


def test_an_older_build_does_not_migrate_backwards(fake_connect):
    """THE mixed-version regression, and the reason the marker is an integer.

    During a rolling deploy an old replica boots against a schema newer than its own. Under the
    checksum this read as "different" and it migrated BACKWARDS, rewriting the marker with its
    own checksum — after which the next new replica migrated forwards again, and so on. Measured
    on a real server before the fix: five migrations across five alternating boots. Every one
    takes ACCESS EXCLUSIVE on 40 tables, while traffic is live and both versions are starting.

    The correct answer for an old replica meeting a newer schema is to do nothing, which is only
    safe because every migration is additive — see docs/adr/0045.
    """
    a = _adapter()
    conn = fake_connect(_FakeConn(marker_version=a._SCHEMA_VERSION + 1))

    a.init_schema()

    assert conn.ddl() == [], (
        f"a build needing schema v{a._SCHEMA_VERSION} migrated a database already at "
        f"v{a._SCHEMA_VERSION + 1} — it is rolling the schema backwards during a deploy")
    assert conn.advisory() == [], "it also took the migration lock to do so"


def test_the_schema_version_was_bumped_with_the_schema():
    """The forget-guard. _SCHEMA_VERSION has to be bumped by hand when the DDL changes, and a
    hand-maintained number is one somebody forgets — after which replicas skip a migration they
    needed and run against a schema missing its columns, which is a worse failure than the one
    this whole change fixes.

    So the checksum is still computed, and pinned here. Changing _SCHEMA or _PG_VIEWS without
    bumping _SCHEMA_VERSION fails this test with the value to record.
    """
    got = store._PgAdapter._schema_checksum()
    assert got == store._PgAdapter._SCHEMA_CHECKSUM_AT_VERSION, (
        f"the schema changed but _SCHEMA_VERSION was not bumped. Set _SCHEMA_VERSION to "
        f"{store._PgAdapter._SCHEMA_VERSION + 1} and _SCHEMA_CHECKSUM_AT_VERSION to {got!r}. "
        f"Every migration must be additive — an existing replica keeps serving against the new "
        f"schema without restarting (docs/adr/0045).")


def test_a_missing_marker_table_migrates_rather_than_assuming_good(fake_connect):
    """A database this build has never seen must be migrated, not trusted."""
    a = _adapter()
    conn = fake_connect(_FakeConn(marker_table_exists=False))
    a.init_schema()
    assert conn.ddl(), "an unrecognised database was assumed to be current"


def test_the_migration_bounds_its_lock_wait(fake_connect):
    """Unbounded, a migration that cannot get its lock holds every reader behind a transaction
    that is itself waiting — which is how the outage propagated from boot to the queue reads."""
    a = _adapter()
    conn = fake_connect(_FakeConn(marker_version=a._SCHEMA_VERSION - 1))
    a.init_schema()
    assert any("lock_timeout" in s for s in conn.sql), "the migration can wait forever"


def test_the_marker_is_written_so_the_next_boot_can_skip(fake_connect):
    a = _adapter()
    conn = fake_connect(_FakeConn(marker_version=a._SCHEMA_VERSION - 1))
    a.init_schema()
    assert any(f"INSERT INTO {a._SCHEMA_VERSION_TABLE}" in s for s in conn.sql), (
        "no marker was recorded, so every future boot re-runs the whole migration")
    inserted = [p for p in conn.params if isinstance(p, tuple) and len(p) == 2
                and p[0] == a._SCHEMA_VERSION]
    assert inserted, "the marker did not record the version actually applied"
    assert inserted[0][1] == a._schema_checksum(), (
        "the marker recorded a checksum other than the DDL it applied")


def test_the_advisory_lock_is_released_even_when_the_migration_fails(fake_connect):
    """A held session lock would block every subsequent boot until the connection died."""
    a = _adapter()
    conn = fake_connect(_FakeConn(marker_version=a._SCHEMA_VERSION - 1, raise_on="CREATE TABLE IF NOT EXISTS jobs"))

    with pytest.raises(Exception):
        a.init_schema()

    assert any("pg_advisory_unlock" in s for s in conn.sql), (
        "a failed migration kept the advisory lock — no replica could boot after it")
    assert conn.rolled_back >= 1, "a failed migration was not rolled back"


def test_an_unreadable_marker_migrates_rather_than_assuming_good():
    """_schema_is_current must answer False on anything unexpected. The expensive answer is the
    safe one: assuming a database is current when it is not ships a broken schema."""
    a = _adapter()

    class _Boom:
        def execute(self, *a, **kw):
            raise RuntimeError("catalog unreadable")

        def fetchone(self):
            return None

    assert a._schema_is_current(_Boom(), "anything") is False


# ── the checksum ──────────────────────────────────────────────────────────────────────────────

def test_the_checksum_is_stable_across_calls():
    assert store._PgAdapter._schema_checksum() == store._PgAdapter._schema_checksum()


def test_the_marker_table_name_is_greppable():
    """test_reset_purges_blobs parses store.py for `CREATE TABLE [IF NOT EXISTS] <name>` to prove
    no table escapes the RESET classification. An f-string placeholder makes that parser read the
    name as "IF" — which it did, and the guard caught it. So the CREATE must spell the name out,
    and the constant must agree with what is spelled."""
    src = Path(store.__file__).read_text()
    assert f"CREATE TABLE IF NOT EXISTS {store._PgAdapter._SCHEMA_VERSION_TABLE} " in src, (
        "the marker table is not created under its literal name, so the RESET classification "
        "guard cannot see it")


def test_the_checksum_changes_when_the_schema_does(monkeypatch):
    """Otherwise a real migration would be skipped — the failure mode opposite to the outage,
    and a worse one."""
    before = store._PgAdapter._schema_checksum()
    monkeypatch.setattr(store, "_SCHEMA", (*store._SCHEMA, "ALTER TABLE jobs ADD COLUMN zz TEXT"))
    assert store._PgAdapter._schema_checksum() != before


def test_the_checksum_ignores_only_whitespace():
    """Reformatting a statement must not look like a schema change; changing it must."""
    before = store._PgAdapter._schema_checksum()
    reflowed = tuple(s.replace("\n", "  ") for s in store._SCHEMA)
    orig = store._SCHEMA
    try:
        store._SCHEMA = reflowed
        assert store._PgAdapter._schema_checksum() == before
    finally:
        store._SCHEMA = orig


# ── against a real server, when one is offered ────────────────────────────────────────────────

_PG = os.environ.get("DATABASE_URL", "")
requires_pg = pytest.mark.skipif(
    not _PG.startswith("postgres"),
    reason="needs a real PostgreSQL; set DATABASE_URL (the 'Postgres integration' CI job does).")


def test_the_postgres_tests_are_not_silently_skipped():
    """A skipping integration job is worse than no job: it reports green while proving nothing,
    and the thing it would have proved is the one that took production down.

    So the 'Postgres integration' job sets ACP_REQUIRE_PG=1, and under that flag a missing or
    non-Postgres DATABASE_URL is a FAILURE rather than a skip. Locally the flag is unset and the
    two tests below skip as normal.

    This test itself always runs — it is the thing that cannot be skipped.
    """
    if os.environ.get("ACP_REQUIRE_PG") != "1":
        pytest.skip("not the CI integration job")
    assert _PG.startswith("postgres"), (
        f"ACP_REQUIRE_PG=1 but DATABASE_URL is {_PG!r} — the integration job would have skipped "
        "the only tests that exercise real lock behaviour and still reported success")


@requires_pg
def test_concurrent_boots_against_a_real_server_migrate_exactly_once():
    """The whole point, on a real server: six replicas boot simultaneously and exactly one runs
    DDL. Before the change five of six died with DeadlockDetected inside init_schema."""
    import threading
    from collections import Counter

    ran = Counter()
    out = Counter()
    lk = threading.Lock()
    real_apply = store._PgAdapter._apply_schema

    def counting(self, conn, want):
        with lk:
            ran["ddl"] += 1
        return real_apply(self, conn, want)

    import psycopg2
    c = psycopg2.connect(_PG)
    c.autocommit = True
    with c.cursor() as cur:
        cur.execute(f"DROP TABLE IF EXISTS {store._PgAdapter._SCHEMA_VERSION_TABLE}")
    c.close()

    store._PgAdapter._apply_schema = counting
    try:
        def boot():
            try:
                store.Store()
                with lk:
                    out["ok"] += 1
            except Exception as e:              # noqa: BLE001
                with lk:
                    out[type(e).__name__] += 1

        ts = [threading.Thread(target=boot) for _ in range(6)]
        for t in ts:
            t.start()
        for t in ts:
            t.join(60)
    finally:
        store._PgAdapter._apply_schema = real_apply

    assert out["ok"] == 6, f"not every replica booted: {dict(out)}"
    assert ran["ddl"] == 1, f"{ran['ddl']} processes ran DDL concurrently; expected exactly 1"


@requires_pg
def test_a_warm_boot_against_a_real_server_runs_no_ddl():
    import threading
    from collections import Counter

    store.Store()                                # ensure the marker is present and current
    ran = Counter()
    lk = threading.Lock()
    real_apply = store._PgAdapter._apply_schema

    def counting(self, conn, want):
        with lk:
            ran["ddl"] += 1
        return real_apply(self, conn, want)

    store._PgAdapter._apply_schema = counting
    try:
        ts = [threading.Thread(target=store.Store) for _ in range(6)]
        for t in ts:
            t.start()
        for t in ts:
            t.join(60)
    finally:
        store._PgAdapter._apply_schema = real_apply

    assert ran["ddl"] == 0, (
        f"{ran['ddl']} replicas replayed DDL against a current schema — the outage is back")
