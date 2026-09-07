"""SharePoint Release is durable, token-safe, and settles verified provider results."""
from types import SimpleNamespace


OWNER = "owner@example.com"
SID = "scan-1"
FILE = "Leave.docx"


class FakeStore:
    def __init__(self):
        self.documents = {}
        self.jobs = None
        self.published = None
        self.root = None
        self.preferred_folder_name = None
        self.receipts = []

    def get_scan(self, scan_id, owner=None):
        return {"run": {"id": scan_id, "source": "sharepoint", "owner_email": OWNER},
                "files": [{"file": FILE, "compliant": 1, "remediated_at": "now"}]}

    def get_file_record(self, scan_id, filename):
        return {"file": filename, "compliant": 1, "remediated_at": "now",
                "drive_file_id": "source-item", "drive_id": "library-1",
                "source_relative_path": "/drives/library-1/root:/HR/Policies"}

    def ensure_release_execution(self, scan_id, owner, source, documents_total,
                                 preferred_folder_name=None):
        self.preferred_folder_name = preferred_folder_name
        return {"id": "release-1", "created_at": "2026-09-05T10:00:00+00:00",
                "folder_name": preferred_folder_name or "2026-09-05 10-00 UTC"}

    def get_release_document(self, release_id, filename, owner):
        return self.documents.get(filename)

    def record_release_document(self, release_id, owner, result):
        self.documents[result["file"]] = dict(result)

    def enqueue_stage_batch(self, scan_id, stage, job_type, payloads, **kwargs):
        self.jobs = (stage, job_type, payloads, kwargs)
        return {"batch_id": "batch-1"}

    def release_status(self, release_id, owner):
        docs = list(self.documents.values())
        return {"id": release_id, "folder_name": "2026-09-05 10-00 UTC",
                "documents_total": 1, "published": sum(d["status"] == "published" for d in docs),
                "failed": sum(d["status"] == "failed" for d in docs), "remaining": 1,
                "roots": []}

    def get_release_root(self, release_id, location, owner):
        return self.root

    def claim_release_root_name(self, release_id, owner, provider, location, name):
        return name

    def record_release_root(self, release_id, owner, provider, location, folder_id, name, url):
        self.root = {"folder_id": folder_id, "folder_name": name, "folder_url": url}
        return self.root

    def record_publish(self, scan_id, filename, published_url=None):
        self.published = (scan_id, filename, published_url)
        return "2026-09-05T10:01:00+00:00"

    def stage_work_item_for_job(self, job_id):
        return {"work_item_id": "work-item-1"} if job_id else None

    def record_side_effect_receipt(self, **receipt):
        self.receipts.append(receipt)
        return receipt


def test_sharepoint_submission_queues_token_free_per_document_work(monkeypatch):
    import core
    from routes.scans import publish_files

    store = FakeStore()
    registered = {}
    monkeypatch.setattr(core, "store", store)
    monkeypatch.setattr(core, "register_scan_tokens",
                        lambda scan_id, **tokens: registered.update(scan_id=scan_id, **tokens))
    request = SimpleNamespace(state=SimpleNamespace(user_email=OWNER),
                              headers={"x-sp-token": "delegated-secret"})

    response = publish_files(SID, request, {"files": [FILE]})

    assert response["queued"] == 1
    assert store.jobs[0:2] == ("release", "publish_file")
    assert store.jobs[2] == [{"scan_id": SID, "release_id": "release-1",
                              "file": FILE, "owner": OWNER}]
    assert "delegated-secret" not in repr(store.jobs)
    assert registered == {"scan_id": SID, "sp": "delegated-secret",
                          "require_shared": True}


def test_sharepoint_submission_saves_a_valid_custom_release_folder(monkeypatch):
    import core
    from routes.scans import publish_files

    store = FakeStore()
    monkeypatch.setattr(core, "store", store)
    monkeypatch.setattr(core, "register_scan_tokens", lambda *args, **kwargs: None)
    request = SimpleNamespace(state=SimpleNamespace(user_email=OWNER),
                              headers={"x-sp-token": "delegated-secret"})
    response = publish_files(
        SID, request,
        {"files": [FILE], "release_folder_name": "Q3 Accessibility Release"})
    assert store.preferred_folder_name == "Q3 Accessibility Release"
    assert response["release_folder_name"] == "Q3 Accessibility Release"


def test_sharepoint_worker_publishes_and_records_verified_copy(monkeypatch):
    import core
    import handlers
    import publish

    store = FakeStore()
    monkeypatch.setattr(core, "store", store)
    monkeypatch.setattr(core, "get_scan_tokens", lambda scan_id: {"sp": "token"})
    monkeypatch.setattr(publish, "ensure_sharepoint_release_folder",
                        lambda *args: {"id": "root-1", "name": "release", "url": "https://sp/root"})
    monkeypatch.setattr(publish, "archive_copy_publish_sharepoint",
                        lambda *args, **kwargs: {"id": "copy-1", "url": "https://sp/copy",
                                                "checksum": "sha256", "created": True,
                                                "filename": "Leave.docx"})

    handlers._publish_file({"scan_id": SID, "release_id": "release-1",
                            "file": FILE, "owner": OWNER},
                           {"attempts": 1, "max_attempts": 5})

    result = store.documents[FILE]
    assert result["status"] == "published"
    assert result["released_relative_path"] == "HR/Policies/Leave.docx"
    assert result["verification"] == "content verified"
    assert store.published == (SID, FILE, "https://sp/copy")


def test_sharepoint_worker_records_canonical_provider_receipt(monkeypatch):
    import core
    import handlers
    import publish

    store = FakeStore()
    monkeypatch.setattr(core, "store", store)
    monkeypatch.setattr(core, "get_scan_tokens", lambda scan_id: {"sp": "token"})
    monkeypatch.setattr(publish, "ensure_sharepoint_release_folder",
                        lambda *args: {"id": "root-1", "name": "release", "url": "https://sp/root"})
    monkeypatch.setattr(publish, "archive_copy_publish_sharepoint",
                        lambda *args, **kwargs: {"id": "copy-1", "url": "https://sp/copy",
                                                "checksum": "sha256:copy", "created": True,
                                                "filename": FILE})
    handlers._publish_file({"scan_id": SID, "release_id": "release-1",
                            "file": FILE, "owner": OWNER},
                           {"id": "job-1", "batch_id": "execution-1",
                            "attempts": 1, "max_attempts": 5})
    assert store.receipts == [{
        "execution_id": "execution-1", "work_item_id": "work-item-1",
        "effect_type": "sharepoint.publish",
        "destination": "graph:library-1:root-1:HR/Policies/Leave.docx",
        "content_digest": "sha256:copy",
        "receipt": {"provider_id": "copy-1", "url": "https://sp/copy", "created": True},
    }]


def test_sharepoint_worker_reuses_claim_after_crash_between_graph_and_database(monkeypatch):
    import core
    import handlers
    import publish
    import pytest

    store = FakeStore()
    monkeypatch.setattr(core, "store", store)
    monkeypatch.setattr(core, "get_scan_tokens", lambda scan_id: {"sp": "token"})
    claimed = []
    monkeypatch.setattr(store, "claim_release_root_name",
                        lambda *args: claimed.append(args[-1]) or args[-1])
    ensured = []
    monkeypatch.setattr(publish, "ensure_sharepoint_release_folder",
                        lambda token, drive, release, name:
                        ensured.append(name) or {"id": "root-1", "name": name,
                                                 "url": "https://sp/root"})
    real_record = store.record_release_root
    attempts = 0

    def record_root(*args):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ConnectionError("worker stopped before the root row committed")
        return real_record(*args)

    monkeypatch.setattr(store, "record_release_root", record_root)
    monkeypatch.setattr(publish, "archive_copy_publish_sharepoint",
                        lambda *args, **kwargs: {"id": "copy-1", "url": "https://sp/copy",
                                                "checksum": "sha256", "created": True,
                                                "filename": FILE})
    payload = {"scan_id": SID, "release_id": "release-1", "file": FILE, "owner": OWNER}

    with pytest.raises(ConnectionError):
        handlers._publish_file(payload, {"attempts": 1, "max_attempts": 5})
    handlers._publish_file(payload, {"attempts": 2, "max_attempts": 5})

    assert claimed == ["2026-09-05 10-00 UTC", "2026-09-05 10-00 UTC"]
    assert ensured == ["2026-09-05 10-00 UTC", "2026-09-05 10-00 UTC"]
    assert store.root["folder_id"] == "root-1"


def test_sharepoint_worker_restores_original_name_after_internal_dedupe(monkeypatch):
    import core
    import handlers
    import publish

    store = FakeStore()
    monkeypatch.setattr(core, "store", store)
    monkeypatch.setattr(core, "get_scan_tokens", lambda scan_id: {"sp": "token"})
    monkeypatch.setattr(store, "get_file_record", lambda scan_id, filename: {
        "file": filename, "source_name": "Report.docx", "compliant": 1,
        "remediated_at": "now", "drive_file_id": "source-2", "drive_id": "library-1",
        "source_relative_path": "/drives/library-1/root:/Legal"})
    monkeypatch.setattr(publish, "ensure_sharepoint_release_folder",
                        lambda *args: {"id": "root-1", "name": "release", "url": "https://sp/root"})
    captured = {}
    def _publish(*args, **kwargs):
        captured.update(internal_name=args[6], source_name=kwargs.get("source_filename"))
        return {"id": "copy-2", "url": "https://sp/copy-2", "checksum": "sha256",
                "created": True, "filename": kwargs["source_filename"]}
    monkeypatch.setattr(publish, "archive_copy_publish_sharepoint", _publish)

    handlers._publish_file({"scan_id": SID, "release_id": "release-1",
                            "file": "Report (1).docx", "owner": OWNER},
                           {"attempts": 1, "max_attempts": 5})

    assert captured == {"internal_name": "Report (1).docx", "source_name": "Report.docx"}
    assert store.documents["Report (1).docx"]["released_relative_path"] == "Legal/Report.docx"


def test_sharepoint_worker_exposes_actionable_expired_session(monkeypatch):
    import core
    import handlers
    import pytest
    from worker import FatalJobError

    store = FakeStore()
    monkeypatch.setattr(core, "store", store)
    monkeypatch.setattr(core, "get_scan_tokens", lambda scan_id: {})

    with pytest.raises(FatalJobError):
        handlers._publish_file({"scan_id": SID, "release_id": "release-1",
                                "file": FILE, "owner": OWNER}, {})

    assert store.documents[FILE]["failure_category"] == "provider_session_expired"
    assert "Reconnect SharePoint" in store.documents[FILE]["explanation"]


def test_sharepoint_worker_retries_a_401_so_silent_refresh_can_replace_the_token(monkeypatch):
    import core
    import handlers
    import publish
    import pytest
    import scanner
    from worker import FatalJobError

    store = FakeStore()
    store.root = {"folder_id": "root-1", "folder_name": "release", "folder_url": "https://sp/root"}
    monkeypatch.setattr(core, "store", store)
    monkeypatch.setattr(core, "get_scan_tokens", lambda scan_id: {"sp": "expired-token"})
    monkeypatch.setattr(publish, "archive_copy_publish_sharepoint",
                        lambda *args, **kwargs: (_ for _ in ()).throw(
                            scanner.SharePointSessionExpired("expired")))
    payload = {"scan_id": SID, "release_id": "release-1", "file": FILE, "owner": OWNER}

    with pytest.raises(scanner.SharePointSessionExpired):
        handlers._publish_file(payload, {"attempts": 1, "max_attempts": 5})
    assert FILE not in store.documents

    with pytest.raises(FatalJobError):
        handlers._publish_file(payload, {"attempts": 5, "max_attempts": 5})
    assert store.documents[FILE]["failure_category"] == "provider_session_expired"
