"""Production-engine concurrency coverage for HITL request idempotency."""
from __future__ import annotations

import os
import sys
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))
import store as store_mod  # noqa: E402

_PG = os.environ.get("DATABASE_URL", "")
pytestmark = pytest.mark.skipif(
    not _PG.startswith("postgres"), reason="needs the disposable PostgreSQL integration job")


def test_concurrent_duplicate_decision_commits_once():
    st = store_mod.Store()
    scan_id = f"hitl-idempotency-{uuid.uuid4()}"
    st.init_scan_run(scan_id, "drive", 1, "t0", "rubric", "hash")
    item_id = st.enqueue_proposals(scan_id, "deck.pptx", "1.1.1", [{
        "locator": "ppt/slides/slide1.xml#Picture 1",
        "proposed_value": "A quarterly revenue chart.",
    }])
    barrier = threading.Barrier(2)

    def decide():
        barrier.wait()
        return st.complete_hitl_decision(
            item_id, "approved", None, None,
            resolution=None, approved_values=["A quarterly revenue chart."],
            actor="reviewer@example.com", detail=None,
            request_id="same-transport-request", expected_version=0)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [future.result() for future in [pool.submit(decide), pool.submit(decide)]]

    assert sorted(replayed for _row, replayed in results) == [False, True]
    row = st.get_hitl_item(item_id)
    assert row["decision_version"] == 1
    assert [d["action"] for d in st.list_decisions(scan_id)] == ["hitl.approved"]
    assert [j["type"] for j in st.list_jobs() if j.get("scan_id") == scan_id] == [
        "apply_approved_values"]


@pytest.mark.parametrize('mutation', ['none', 'review_changed_upload', 'consent_changed_upload', 'serialized_review_note'])
def test_office_retry_commit_rechecks_exact_authority_on_postgres(monkeypatch, mutation):
    """Use the actual queued Office writer on a separate guarded disposable database.

    Review and standing consent changes during the external immutable upload must
    leave the original pointer and contribution unchanged. The unchanged control
    proves the real PostgreSQL FOR UPDATE/CAS branch still commits verified bytes.
    """
    import psycopg2
    from psycopg2 import sql
    from urllib.parse import urlparse
    from conftest import require_disposable_postgres
    import test_office_verified_retry as fixture
    from proposals import Verification
    # This job isolates PostgreSQL commit/lock semantics. The full backend fixture
    # separately invokes the actual Office scanner; this job has no .NET runtime.
    def caption_presence(data, filename):
        target=fixture.image_target(data, fixture.LOC)
        return Verification(True, set() if target and target[0] else {'1.1.1'})
    monkeypatch.setattr(fixture,'verify_residual',caption_presence)
    require_disposable_postgres(_PG)
    admin=psycopg2.connect(_PG)
    admin.autocommit=True
    require_disposable_postgres(_PG, conn=admin)
    name='office_retry_' + uuid.uuid4().hex + '_test'
    st=None
    try:
        with admin.cursor() as cur:
            cur.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
        isolated=urlparse(_PG)._replace(path='/' + name).geturl()
        require_disposable_postgres(isolated)
        monkeypatch.setattr(store_mod, '_DATABASE_URL', isolated)
        st=store_mod.Store()
        assert st._db.supports_for_update and st._db.supports_skip_locked
        worker=None; completed=threading.Event(); started=threading.Event(); shared={}
        if mutation=='serialized_review_note':
            from time import monotonic, sleep
            actual_cas=st.compare_and_set_retry_artifact
            def commit_with_competing_note(*args, **kwargs):
                def competing_note():
                    connection=psycopg2.connect(isolated)
                    try:
                        connection.autocommit=True
                        shared['pid']=connection.get_backend_pid()
                        with connection.cursor() as cur:
                            cur.execute("SET lock_timeout='3s'")
                            started.set()
                            cur.execute("UPDATE hitl_queue SET reviewer_note='concurrent note' WHERE scan_id='scan' AND file='file.docx'")
                    except Exception as exc:
                        shared['error']=exc
                    finally:
                        connection.close(); completed.set()
                nonlocal worker
                worker=threading.Thread(target=competing_note)
                worker.start(); assert started.wait(1)
                deadline=monotonic()+1; locked=False
                while monotonic()<deadline:
                    with admin.cursor() as cur:
                        cur.execute('SELECT wait_event_type FROM pg_stat_activity WHERE pid=%s',(shared['pid'],))
                        row=cur.fetchone();locked=bool(row and row[0]=='Lock')
                    if locked:break
                    sleep(.01)
                assert locked and not completed.is_set()
                return actual_cas(*args, **kwargs)
            monkeypatch.setattr(st,'compare_and_set_retry_artifact',commit_with_competing_note)
        fixture.test_live_adapter_uses_restored_frozen_run_and_only_next_settled_model(st, monkeypatch,
            'none' if mutation=='serialized_review_note' else mutation)
        if worker is not None:
            worker.join(3)
            assert completed.is_set() and 'error' not in shared

    finally:
        if st is not None and st._db._pool is not None:
            st._db._pool.closeall()
        with admin.cursor() as cur:
            cur.execute(sql.SQL('DROP DATABASE IF EXISTS {} WITH (FORCE)').format(sql.Identifier(name)))
        admin.close()
