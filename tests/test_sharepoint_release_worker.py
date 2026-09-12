"""SharePoint Release is durable, token-safe, and settles verified provider results."""
from types import SimpleNamespace
import hashlib
import pytest
DIGEST = hashlib.sha256(b"corrected fixture").hexdigest()

@pytest.fixture(autouse=True)
def corrected_blob(monkeypatch):
    import publish
    monkeypatch.setattr(publish._blob, "download_remediated", lambda *args: b"corrected fixture")



OWNER = "owner@example.com"
SID = "scan-1"
FILE = "Leave.docx"


class FakeStore:
    def set_job_phase(self, *args):
        pass

    def __init__(self):
        self.documents = {}
        self.jobs = None
        self.published = None
        self.root = None
        self.preferred_folder_name = None
        self.parent_folder_id = None
        self.parent_folder_name = None
        self.receipts = []
        self.finding_lineage = None

    def get_scan(self, scan_id, owner=None):
        return {"run": {"id": scan_id, "source": "sharepoint", "owner_email": OWNER},
                "files": [{"file": FILE, "compliant": 1, "remediated_at": "now"}]}

    def get_decisions(self, scan_id, owner=None):
        return {}

    def get_file_record(self, scan_id, filename):
        return {"file": filename, "compliant": 1, "remediated_at": "now",
                "drive_file_id": "source-item", "drive_id": "library-1",
                "corrected_sha256": DIGEST,
                "source_relative_path": "/drives/library-1/root:/HR/Policies"}

    def ensure_release_execution(self, scan_id, owner, source, documents_total,
                                 preferred_folder_name=None, parent_folder_id=None,
                                 parent_folder_name=None):
        self.preferred_folder_name = preferred_folder_name
        self.parent_folder_id = parent_folder_id
        self.parent_folder_name = parent_folder_name
        return {"id": "release-1", "created_at": "2026-09-05T10:00:00+00:00",
                "folder_name": preferred_folder_name or "2026-09-05 10-00 UTC",
                "parent_folder_id": parent_folder_id,
                "parent_folder_name": parent_folder_name}

    def get_release_document(self, release_id, filename, owner):
        return self.documents.get(filename)

    def record_release_document(self, release_id, owner, result):
        self.documents[result["file"]] = dict(result)

    def enqueue_stage_batch(self, scan_id, stage, job_type, payloads, **kwargs):
        self.jobs = (stage, job_type, payloads, kwargs)
        return {"batch_id": "batch-1"}

    def release_status(self, release_id, owner):
        docs = list(self.documents.values())
        return {"id": release_id, "scan_id": SID, "folder_name": "2026-09-05 10-00 UTC",
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

    def release_finding_lineage(self, execution_id, filename):
        return self.finding_lineage


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
                              "file": FILE, "owner": OWNER, "artifact_digest": f"sha256:{DIGEST}", "remediated_at": "now"}]
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
    assert store.preferred_folder_name.endswith(f" - {OWNER} - Q3 Accessibility Release")
    assert response["release_folder_name"] == store.preferred_folder_name


def test_sharepoint_submission_freezes_the_preflighted_parent_for_worker_retries(monkeypatch):
    import core
    from routes import scans

    store = FakeStore()
    monkeypatch.setattr(core, "store", store)
    monkeypatch.setattr(core, "register_scan_tokens", lambda *args, **kwargs: None)
    monkeypatch.setattr(scans, "_preflight_release_destination", lambda request, destination: {
        "ready": True, "folder_reachable": True, "write_permission": True})
    request = SimpleNamespace(state=SimpleNamespace(user_email=OWNER),
                              headers={"x-sp-token": "delegated-secret"})
    response = scans.publish_files(SID, request, {"files": [FILE], "destination": {
        "provider": "sharepoint", "folder_id": "finance-drive/approved-folder",
        "folder_name": "Approved releases"}})
    assert store.parent_folder_id == "finance-drive/approved-folder"
    assert store.parent_folder_name == "Approved releases"
    assert response["parent_folder_id"] == "finance-drive/approved-folder"


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
    store.finding_lineage = {
        "upstream_execution_id": "remediation-1",
        "snapshot_id": "assessment-snapshot-1",
        "findings": [
            {"finding_id": "finding-a", "disposition": "resolved_verified", "revision": 2},
            {"finding_id": "finding-b", "disposition": "excluded", "revision": 1},
        ],
    }
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
        "content_digest": DIGEST,
        "receipt": {
            "corrected_copy_assessment": {"fixture_assessment": True},
            "provider_id": "copy-1", "url": "https://sp/copy", "created": True,
            "checksum": "sha256:copy", "filename": FILE, "verified": True,
            "finding_lineage": {
                "upstream_execution_id": "remediation-1",
                "snapshot_id": "assessment-snapshot-1",
                "findings": [
                    {"finding_id": "finding-a", "disposition": "resolved_verified", "revision": 2},
                    {"finding_id": "finding-b", "disposition": "excluded", "revision": 1},
                ],
            },
        },
    }]


def test_sharepoint_worker_freezes_lineage_before_release_document_write(monkeypatch):
    import core
    import handlers
    import publish

    store = FakeStore()
    store.finding_lineage = {
        "upstream_execution_id": "remediation-1", "snapshot_id": "assessment-snapshot-1",
        "findings": [
            {"finding_id": "finding-a", "disposition": "resolved_verified", "revision": 3},
        ],
    }
    ordering = []
    real_receipt = store.record_side_effect_receipt
    real_document = store.record_release_document
    monkeypatch.setattr(store, "record_side_effect_receipt",
                        lambda **receipt: ordering.append("receipt") or real_receipt(**receipt))
    monkeypatch.setattr(store, "record_release_document",
                        lambda *args: ordering.append("document") or real_document(*args))
    monkeypatch.setattr(core, "store", store)
    monkeypatch.setattr(core, "get_scan_tokens", lambda scan_id: {"sp": "token"})
    monkeypatch.setattr(publish, "ensure_sharepoint_release_folder",
                        lambda *args: {"id": "root-1", "name": "release", "url": "https://sp/root"})
    monkeypatch.setattr(publish, "archive_copy_publish_sharepoint",
                        lambda *args, **kwargs: {"id": "copy-1", "url": "https://sp/copy",
                                                "checksum": "sha256:copy", "created": False,
                                                "filename": FILE})

    handlers._publish_file(
        {"scan_id": SID, "release_id": "release-1", "file": FILE, "owner": OWNER},
        {"id": "job-1", "batch_id": "execution-1", "attempts": 1, "max_attempts": 5})

    assert ordering[-2:] == ["receipt", "document"]
    assert store.receipts[0]["receipt"]["finding_lineage"] == store.finding_lineage


def test_sharepoint_worker_reserves_before_provider_and_finalizes_before_document(monkeypatch):
    import core
    import handlers
    import publish

    store = FakeStore()
    events = []
    store.reserve_side_effect = lambda **kwargs: events.append(("reserve", kwargs)) or {
        "effect_id": "effect-1", "status": "reserved", "acquired": True,
        "reclaimed": False, "reused": False, "reservation_token": "token-1"}
    store.finalize_side_effect = lambda effect_id, token, receipt: \
        events.append(("finalize", effect_id, token, receipt)) or {"status": "completed"}
    real_document = store.record_release_document
    monkeypatch.setattr(store, "record_release_document",
                        lambda *args: events.append(("document",)) or real_document(*args))
    monkeypatch.setattr(core, "store", store)
    monkeypatch.setattr(core, "get_scan_tokens", lambda scan_id: {"sp": "token"})
    monkeypatch.setattr(publish, "ensure_sharepoint_release_folder",
                        lambda *args: {"id": "root-1", "name": "release", "url": "https://sp/root"})
    monkeypatch.setattr(publish, "archive_copy_publish_sharepoint",
                        lambda *args, **kwargs: events.append(("provider",)) or {
                            "id": "copy-1", "url": "https://sp/copy", "checksum": DIGEST,
                            "created": True, "verified": True, "filename": FILE})

    handlers._publish_file(
        {"scan_id": SID, "release_id": "release-1", "file": FILE, "owner": OWNER},
        {"id": "job-1", "batch_id": "execution-1", "locked_by": "worker-1",
         "attempts": 1, "max_attempts": 5})

    assert [event[0] for event in events] == ["reserve", "provider", "finalize", "document"]
    assert events[0][1]["content_digest"] == DIGEST
    assert events[2][1:3] == ("effect-1", "token-1")


def test_completed_sharepoint_reservation_reuses_verified_receipt_without_provider_write(monkeypatch):
    import core
    import handlers
    import publish

    store = FakeStore()
    store.reserve_side_effect = lambda **kwargs: {
        "effect_id": "effect-1", "status": "completed", "acquired": False,
        "reused": True, "receipt": {"provider_id": "copy-1", "url": "https://sp/copy",
                                    "checksum": DIGEST, "filename": FILE,
                                    "created": False, "verified": True}}
    monkeypatch.setattr(core, "store", store)
    monkeypatch.setattr(core, "get_scan_tokens", lambda scan_id: {"sp": "token"})
    monkeypatch.setattr(publish, "ensure_sharepoint_release_folder",
                        lambda *args: {"id": "root-1", "name": "release", "url": "https://sp/root"})
    monkeypatch.setattr(publish, "archive_copy_publish_sharepoint",
                        lambda *args, **kwargs: (_ for _ in ()).throw(
                            AssertionError("completed reservation must not repeat provider I/O")))

    handlers._publish_file(
        {"scan_id": SID, "release_id": "release-1", "file": FILE, "owner": OWNER},
        {"id": "job-1", "batch_id": "execution-1", "attempts": 2, "max_attempts": 5})

    assert store.documents[FILE]["released_document_id"] == "copy-1"
    assert store.documents[FILE]["verification"] == "content verified"


def test_busy_sharepoint_reservation_retries_without_provider_write(monkeypatch):
    import core
    import handlers
    import publish
    import pytest

    store = FakeStore()
    store.reserve_side_effect = lambda **kwargs: {
        "effect_id": "effect-1", "status": "reserved", "acquired": False,
        "reused": False, "reservation_owner": "other-worker"}
    monkeypatch.setattr(core, "store", store)
    monkeypatch.setattr(core, "get_scan_tokens", lambda scan_id: {"sp": "token"})
    monkeypatch.setattr(publish, "ensure_sharepoint_release_folder",
                        lambda *args: {"id": "root-1", "name": "release", "url": "https://sp/root"})
    monkeypatch.setattr(publish, "archive_copy_publish_sharepoint",
                        lambda *args, **kwargs: (_ for _ in ()).throw(
                            AssertionError("busy reservation must not perform provider I/O")))

    with pytest.raises(RuntimeError, match="another worker"):
        handlers._publish_file(
            {"scan_id": SID, "release_id": "release-1", "file": FILE, "owner": OWNER},
            {"id": "job-1", "batch_id": "execution-1", "attempts": 1, "max_attempts": 5})


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
        "corrected_sha256": DIGEST,
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

class PartialStore(FakeStore):
    def __init__(self):
        super().__init__()
        self.audit = []

    def get_file_record(self, sid, filename):
        return {**super().get_file_record(sid, filename), "compliant": 0,
                "issues": [{"wcag": "SC_1_1_1", "severity": "SERIOUS"}]}

    def get_scan(self, sid, owner=None):
        return {**super().get_scan(sid, owner), "files": [self.get_file_record(sid, FILE)]}

    def log_decision(self, *args, **kwargs):
        self.audit.append((args, kwargs))


def test_partial_release_requires_explicit_current_artifact_and_preserves_issues(monkeypatch):
    import core, handlers, publish, json
    from routes.scans import publish_files
    from fastapi import HTTPException
    store = PartialStore()
    monkeypatch.setattr(core, "store", store)
    monkeypatch.setattr(core, "register_scan_tokens", lambda *a, **kw: None)
    request = SimpleNamespace(state=SimpleNamespace(user_email=OWNER), headers={"x-sp-token": "token"})
    strict = publish_files(SID, request, {"files": [FILE]})
    assert strict["queued"] == 0
    with pytest.raises(HTTPException) as exc:
        publish_files(SID, request, {"files": [FILE], "allow_remaining_issues": True})
    assert exc.value.status_code == 409
    response = publish_files(SID, request, {"files": [FILE], "allow_remaining_issues": True,
                                           "expected_artifacts": {FILE: DIGEST}})
    assert response["queued"] == 1
    payload = store.jobs[2][0]
    assert payload["allow_remaining_issues"] is True
    evidence = json.loads(store.audit[-1][1]["detail"])
    assert evidence["compliant"] is False
    assert evidence["remaining_issue_count"] == 1
    assert evidence["artifact_digest"] == f"sha256:{DIGEST}"
    monkeypatch.setattr(core, "get_scan_tokens", lambda sid: {"sp": "token"})
    monkeypatch.setattr(publish, "ensure_sharepoint_release_folder", lambda *a: {"id": "root-1", "name": "release"})
    monkeypatch.setattr(publish, "archive_copy_publish_sharepoint", lambda *a, **kw: {
        "id": "copy-1", "url": "https://sp/copy", "checksum": DIGEST, "created": True, "filename": FILE})
    handlers._publish_file(payload, {"id": "job-1", "batch_id": "execution-1", "attempts": 1})
    assert store.documents[FILE]["status"] == "published"
    assert store.receipts[-1]["receipt"]["release_review"]["remaining_issue_count"] == 1
    assert store.get_file_record(SID, FILE)["compliant"] == 0


def test_partial_release_worker_still_rejects_changed_corrected_bytes(monkeypatch):
    import core, handlers
    from worker import FatalJobError
    store = PartialStore()
    monkeypatch.setattr(core, "store", store)
    monkeypatch.setattr(core, "get_scan_tokens", lambda sid: {"sp": "token"})
    with pytest.raises(FatalJobError):
        handlers._publish_file({"scan_id": SID, "release_id": "release-1", "file": FILE,
            "owner": OWNER, "allow_remaining_issues": True, "artifact_digest": "sha256:stale",
            "remediated_at": "now"}, {"attempts": 1})
    assert store.published is None


@pytest.fixture(autouse=True)
def _candidate_assessment_for_delivery_fixture(monkeypatch):
    # Provider/fencing fixtures intentionally use sentinel bytes; the actual
    # document gate is proven by test_release_candidate_assessment.
    import release_candidate_assessment
    monkeypatch.setattr(release_candidate_assessment, 'assess_candidate',
                        lambda *args, **kwargs: {'fixture_assessment': True})
