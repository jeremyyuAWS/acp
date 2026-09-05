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

    def get_scan(self, scan_id, owner=None):
        return {"run": {"id": scan_id, "source": "sharepoint", "owner_email": OWNER},
                "files": [{"file": FILE, "compliant": 1, "remediated_at": "now"}]}

    def get_file_record(self, scan_id, filename):
        return {"file": filename, "compliant": 1, "remediated_at": "now",
                "drive_file_id": "source-item", "drive_id": "library-1",
                "source_relative_path": "/drives/library-1/root:/HR/Policies"}

    def ensure_release_execution(self, scan_id, owner, source, documents_total):
        return {"id": "release-1", "created_at": "2026-09-05T10:00:00+00:00",
                "folder_name": "2026-09-05 10-00 UTC"}

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

    def record_release_root(self, release_id, owner, provider, location, folder_id, name, url):
        self.root = {"folder_id": folder_id, "folder_name": name, "folder_url": url}
        return self.root

    def record_publish(self, scan_id, filename, published_url=None):
        self.published = (scan_id, filename, published_url)
        return "2026-09-05T10:01:00+00:00"


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
    assert registered == {"scan_id": SID, "sp": "delegated-secret"}


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
                        lambda *args: {"id": "copy-1", "url": "https://sp/copy",
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
