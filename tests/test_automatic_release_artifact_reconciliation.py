"""A changed copy before admission is recoverable; admitted copies stay frozen."""
import automatic_release as flow
import pytest
from test_automatic_release_service import prepared, authorize, tick, OWNER, SID, FILE, DIGEST


def test_corrected_copy_race_before_admission_recovers_on_next_tick(prepared, monkeypatch):
    """Q3 remains valid for current written bytes until any delivery is admitted."""
    row = authorize(prepared)
    real = flow.require_current_record
    changed = False
    latest = 'b' * 64

    def intervening_write(store, sid, filename, digest, remediated_at, **kwargs):
        nonlocal changed
        if not changed:
            changed = True
            with store._db.cursor() as cur:
                store._db.execute(cur, "UPDATE file_records SET corrected_sha256=%s,remediated_at=%s WHERE scan_id=%s AND file=%s",
                                  (latest, '2026-09-09T00:01:00Z', sid, filename))
        return real(store, sid, filename, digest, remediated_at, **kwargs)

    monkeypatch.setattr(flow, 'require_current_record', intervening_write)
    blocked = tick(prepared, row)
    assert not prepared.calls
    assert blocked['progress']['files'][FILE]['state'] == 'blocked'
    assert not blocked['progress']['files'][FILE].get('artifact_digest')
    resumed = tick(prepared, blocked)
    assert len(prepared.calls) == 1
    assert prepared.calls[0]['expected_artifacts'] == {FILE: latest}
    assert resumed['progress']['files'][FILE]['artifact_digest'] == latest


def test_changed_copy_after_admission_cannot_rebuy_delivery(prepared):
    row = authorize(prepared)
    admitted = tick(prepared, row)
    with prepared.store._db.cursor() as cur:
        prepared.store._db.execute(cur, "UPDATE file_records SET corrected_sha256=%s WHERE scan_id=%s", ('b' * 64, SID))
    reconciled = tick(prepared, admitted)
    assert len(prepared.calls) == 1
    assert reconciled['progress']['files'][FILE]['artifact_digest'] == DIGEST
    assert reconciled['progress']['files'][FILE]['state'] != 'published'


def test_same_admitted_bytes_with_new_timestamp_use_fresh_admission_metadata(prepared):
    row = authorize(prepared)
    flow.publish_admission(prepared.store, row['id'], OWNER, SID, FILE, DIGEST)
    current_timestamp = '2026-09-09T00:01:00Z'
    with prepared.store._db.cursor() as cur:
        prepared.store._db.execute(cur, "UPDATE file_records SET remediated_at=%s WHERE scan_id=%s", (current_timestamp, SID))
    payload = dict(automatic_release_id=row['id'], owner=OWNER, scan_id=SID, file=FILE,
                   artifact_digest='sha256:' + DIGEST, remediated_at='2026-09-09T00:00:00Z')

    def preflight_only(current, job):
        # Actual handler's exact-copy preflight. No provider mutation in this fixture.
        result = flow.require_current_record(prepared.store, SID, FILE, DIGEST,
                                             current['remediated_at'], owner=OWNER)
        assert result['remediated_at'] == current_timestamp
        assert current['artifact_digest'] == payload['artifact_digest']
        return 'safe preflight'

    assert flow.publish_job(prepared.store, payload, {}, preflight_only) == 'safe preflight'
    assert payload['remediated_at'] == '2026-09-09T00:00:00Z'


def test_fresh_timestamp_never_readmits_different_corrected_bytes(prepared):
    from worker import FatalJobError
    row = authorize(prepared)
    flow.publish_admission(prepared.store, row['id'], OWNER, SID, FILE, DIGEST)
    with prepared.store._db.cursor() as cur:
        prepared.store._db.execute(cur, "UPDATE file_records SET corrected_sha256=%s,remediated_at=%s WHERE scan_id=%s",
                                  ('b' * 64, '2026-09-09T00:01:00Z', SID))
    payload = dict(automatic_release_id=row['id'], owner=OWNER, scan_id=SID, file=FILE,
                   artifact_digest='sha256:' + DIGEST, remediated_at='2026-09-09T00:00:00Z')
    with pytest.raises(FatalJobError, match='artifact changed'):
        flow.publish_job(prepared.store, payload, {}, lambda *args: pytest.fail('Different bytes must never reach the provider callback'))
