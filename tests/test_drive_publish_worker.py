"""Drive workers reconcile exact durable IDs across an interrupted provider write."""
import hashlib
from types import SimpleNamespace

import pytest

from test_sharepoint_release_worker import FakeStore, OWNER, SID, FILE, DIGEST

DATA = b"corrected fixture"


class Result:
    def __init__(self, value=None, error=None):
        self.value, self.error = value, error

    def execute(self):
        if self.error:
            raise self.error
        return self.value


def http_error(status):
    error = IOError("provider secret text must not escape")
    error.resp = SimpleNamespace(status=status)
    return error


class Drive:
    def __init__(self):
        self.items = {}
        self.created = []
        self.fail_after_create = False
        self.search_pages = None

    def files(self):
        return self

    def generateIds(self, **kwargs):
        return Result({"ids": ["planned-1"]})

    def get(self, fileId, **kwargs):
        if fileId not in self.items:
            return Result(error=http_error(404))
        return Result(self.items[fileId][0])

    def list(self, **kwargs):
        if self.search_pages is not None:
            return Result(self.search_pages.get(kwargs.get("pageToken"), {"files": []}))
        # Simulate an eventually consistent search index which sees no recently created copy.
        return Result({"files": []})

    def create(self, body, media_body, **kwargs):
        item_id = body.get("id", "unreserved")
        if item_id in self.items:
            return Result(error=http_error(409))
        content = media_body.getbytes(0, media_body.size())
        item = {**body, "id": item_id, "webViewLink": "https://drive/copy"}
        self.items[item_id] = (item, content)
        self.created.append(item_id)
        return Result(error=TimeoutError("connection ended") if self.fail_after_create else None,
                      value=item)

    def get_media(self, fileId):
        return Result(self.items[fileId][1])


@pytest.fixture
def worker(monkeypatch):
    import core
    import handlers
    import publish
    store = FakeStore()
    store.get_scan = lambda *args, **kwargs: {"run": {"source": "drive"}}
    store.get_file_record = lambda *args: {"file": FILE, "compliant": 1,
        "remediated_at": "now", "corrected_sha256": DIGEST,
        "drive_file_id": "source-1", "source_relative_path": FILE}
    store.root = {"folder_id": "root-1"}
    store.reservation = {"effect_id": "effect-1", "reservation_token": "lease-1",
                         "status": "reserved", "acquired": True, "receipt": {}}
    store.reserve_side_effect = lambda **kwargs: store.reservation
    store.finalize_side_effect = lambda *args: store.receipts.append(args)
    def planned(effect, token, candidate):
        store.reservation["receipt"]["planned_provider_id"] = candidate
        return candidate
    store.prepare_side_effect_provider_id = planned
    svc = Drive()
    monkeypatch.setattr(core, "store", store)
    monkeypatch.setattr(core, "get_scan_tokens", lambda *args: {"drive": "secret-token"})
    monkeypatch.setattr(handlers, "_drive_client", lambda token: svc)
    monkeypatch.setattr(publish._blob, "download_remediated", lambda *args: DATA)
    payload = {"scan_id": SID, "release_id": "release-1", "file": FILE,
               "owner": OWNER, "artifact_digest": f"sha256:{DIGEST}", "remediated_at": "now"}
    job = {"id": "job-1", "batch_id": "execution-1", "attempts": 1, "max_attempts": 5}
    return store, svc, payload, job


def test_timeout_after_write_reuses_reserved_id_even_when_search_is_empty(worker):
    import handlers
    from worker import ReservationRetryError
    store, svc, payload, job = worker
    svc.fail_after_create = True
    with pytest.raises(ReservationRetryError) as error:
        handlers._publish_file_guarded(payload, job)
    assert error.value.retry_after_seconds >= 300
    assert store.reservation["receipt"]["planned_provider_id"] == "planned-1"
    assert not store.documents and not store.receipts
    svc.fail_after_create = False
    store.reservation.update(reclaimed=True, reservation_token="lease-2")
    handlers._publish_file_guarded(payload, {**job, "attempts": 2})
    assert svc.created == ["planned-1"]
    assert store.documents[FILE]["status"] == "published"
    assert store.documents[FILE]["artifact_digest"] == f"sha256:{DIGEST}"
    assert store.receipts[0][2]["provider_id"] == "planned-1"


def test_legacy_uncertain_write_without_matching_marker_never_creates(worker):
    import handlers
    from worker import FatalJobError
    store, svc, payload, job = worker
    store.reservation["reclaimed"] = True
    with pytest.raises(FatalJobError, match="earlier Google Drive delivery"):
        handlers._publish_file_guarded(payload, job)
    assert not svc.created
    assert store.documents[FILE]["failure_category"] == "delivery_version_unresolved"


def test_missing_drive_grant_stops_before_provider(worker, monkeypatch):
    import core
    import handlers
    from worker import FatalJobError
    store, svc, payload, job = worker
    monkeypatch.setattr(core, "get_scan_tokens", lambda *args: {})
    with pytest.raises(FatalJobError, match="Google Drive session expired"):
        handlers._publish_file_guarded(payload, job)
    assert not svc.created
    assert store.documents[FILE]["failure_category"] == "provider_session_expired"


def test_changed_artifact_does_not_write(worker):
    import handlers
    from worker import FatalJobError
    store, svc, payload, job = worker
    with pytest.raises(FatalJobError, match="artifact changed"):
        handlers._publish_file_guarded({**payload, "artifact_digest": "sha256:wrong"}, job)
    assert not svc.created


def test_reserved_copy_with_changed_bytes_is_not_overwritten(worker):
    import handlers
    from worker import ReservationRetryError
    store, svc, payload, job = worker
    store.reservation["receipt"]["planned_provider_id"] = "planned-1"
    svc.items["planned-1"] = ({"id": "planned-1", "parents": ["root-1"],
        "properties": {"acpPublishKey": __import__('publish').publication_key(SID, "source-1", DIGEST)}}, b"wrong")
    with pytest.raises(ReservationRetryError):
        handlers._publish_file_guarded(payload, job)
    assert not svc.created and not store.receipts


def test_drive_search_follows_empty_first_page_before_legacy_reuse():
    import publish
    svc = Drive()
    item = {"id": "old-copy", "name": "report.pdf"}
    svc.items["old-copy"] = (item, DATA)
    svc.search_pages = {None: {"files": [], "nextPageToken": "page-2"},
                        "page-2": {"files": [item]}}
    result = publish.upload_published(svc, "root", "report.pdf", DATA,
                                     idempotency_key="key", reconcile_only=True, return_details=True)
    assert result["id"] == "old-copy" and result["verified"]
    assert not svc.created


@pytest.mark.parametrize("page", [{"incompleteSearch": True},
                                    {"files": [], "nextPageToken": "same"}])
def test_incomplete_or_repeating_search_never_creates(page):
    import publish
    svc = Drive()
    svc.search_pages = {None: page, "same": page}
    with pytest.raises(IOError):
        publish.upload_published(svc, "root", "report.pdf", DATA, idempotency_key="key")
    assert not svc.created


def test_missing_checksum_requires_downloaded_bytes_not_a_success_identifier():
    import publish
    svc = Drive()
    svc.items["copy"] = ({"id": "copy"}, b"wrong")
    svc.search_pages = {None: {"files": [{"id": "copy"}]}}
    with pytest.raises(IOError, match="content verification"):
        publish.upload_published(svc, "root", "report.pdf", DATA, idempotency_key="key")
    assert not svc.created


def test_create_conflict_rechecks_reserved_id_without_overwrite():
    import publish
    class ConcurrentDrive(Drive):
        def create(self, body, media_body, **kwargs):
            super().create(body, media_body, **kwargs)
            return Result(error=http_error(409))
    svc = ConcurrentDrive()
    result = publish.upload_published(svc, "root", "report.pdf", DATA,
                                     idempotency_key="key", target_file_id="planned-1",
                                     return_details=True)
    assert result["id"] == "planned-1" and result["created"] is False
    assert svc.created == ["planned-1"]


def test_reserved_id_at_different_destination_is_not_reused_or_overwritten():
    import publish
    svc = Drive()
    svc.items["planned-1"] = ({"id": "planned-1", "parents": ["someone-else"],
                               "properties": {"acpPublishKey": "key"}}, DATA)
    with pytest.raises(IOError, match="identity no longer matches"):
        publish.upload_published(svc, "root", "report.pdf", DATA,
                                 idempotency_key="key", target_file_id="planned-1")
    assert not svc.created


def test_stale_worker_fencing_token_never_records_publication(worker):
    import handlers
    from worker import ReservationRetryError
    store, svc, payload, job = worker
    store.finalize_side_effect = lambda *args: (_ for _ in ()).throw(RuntimeError("stale token"))
    with pytest.raises(ReservationRetryError):
        handlers._publish_file_guarded(payload, job)
    assert svc.created == ["planned-1"]
    assert not store.documents and store.published is None


def test_busy_reservation_does_not_upload_or_allocate_id(worker):
    import handlers
    from worker import ReservationRetryError
    store, svc, payload, job = worker
    store.reservation.update(acquired=False)
    with pytest.raises(ReservationRetryError):
        handlers._publish_file_guarded(payload, job)
    assert not svc.created and not store.reservation["receipt"]


@pytest.mark.parametrize("status", [401, 403])
def test_expired_or_refused_access_marks_automatic_release_reconnect(worker, monkeypatch, status):
    import handlers
    import automatic_release_store
    from worker import FatalJobError
    store, svc, payload, job = worker
    updates = []
    monkeypatch.setattr(automatic_release_store, "update_file", lambda *args: updates.append(args[-1]))
    svc.get = lambda **kwargs: Result(error=http_error(status))
    with pytest.raises(FatalJobError, match="access needs reconnecting"):
        handlers._publish_file_guarded({**payload, "automatic_release_id": "auto-1"}, job)
    assert updates[0]["requires_reconnect"] is True
    assert not svc.created


def test_legacy_missing_release_root_does_not_create_folders(worker):
    import handlers
    from worker import FatalJobError
    store, svc, payload, job = worker
    store.root = None
    store.reservation["reclaimed"] = True
    with pytest.raises(FatalJobError, match="earlier Google Drive release folder"):
        handlers._publish_file_guarded(payload, job)
    assert not svc.created and store.root is None


def test_legacy_missing_relative_folder_does_not_create_folders(worker, monkeypatch):
    import handlers
    from worker import FatalJobError
    store, svc, payload, job = worker
    record = store.get_file_record(SID, FILE)
    store.get_file_record = lambda *args: {**record, "source_relative_path": "Policies/" + FILE}
    store.reservation["reclaimed"] = True
    with pytest.raises(FatalJobError, match="earlier Google Drive destination"):
        handlers._publish_file_guarded(payload, job)
    assert not svc.created


def test_release_folder_lookup_uses_supported_sort_and_follows_pagination():
    import publish
    class FolderDrive(Drive):
        def list(self, **kwargs):
            assert kwargs["orderBy"] == "createdTime"  # Drive does not support an 'id' sort key.
            return super().list(**kwargs)
    svc = FolderDrive()
    svc.search_pages = {None: {"files": [], "nextPageToken": "second"},
                        "second": {"files": [{"id": "existing-root"}]}}
    assert publish._find_folder(svc, "parent", name="Remediated")["id"] == "existing-root"
