"""Drive and local Release use canonical job-less work and durable effect receipts."""
from types import SimpleNamespace


OWNER = "owner@example.com"


def test_jobless_release_reuses_identity_and_recovers_only_failed_items(isolated_store):
    sid = "sync-release-store"
    isolated_store.enqueue_scan(sid, "local", OWNER, "scan_discover", {"scan_id": sid},
                                inputs={"source": "local"})
    fingerprint = isolated_store.canonical_request_fingerprint({"files": ["a.pdf", "b.pdf"]})
    execution = isolated_store.ensure_synchronous_stage_execution(
        scan_id=sid, stage="release", input_ids=["b.pdf", "a.pdf"],
        input_snapshot_id="remediate-snapshot", request_fingerprint=fingerprint)
    assert execution["reused"] is False
    with isolated_store._db.cursor() as cur:
        isolated_store._db.execute(cur, "SELECT COUNT(*) AS n FROM jobs WHERE batch_id=%s",
                                   (execution["execution_id"],))
        assert isolated_store._db.fetchone(cur)["n"] == 0
        isolated_store._db.execute(cur, "SELECT COUNT(*) AS n FROM stage_outbox WHERE execution_id=%s",
                                   (execution["execution_id"],))
        assert isolated_store._db.fetchone(cur)["n"] == 0

    isolated_store.finish_synchronous_stage_item(
        execution["execution_id"], "a.pdf", outcome="completed", result={"file": "a.pdf"})
    isolated_store.finish_synchronous_stage_item(
        execution["execution_id"], "b.pdf", outcome="failed", result={"file": "b.pdf"})
    failed = isolated_store.stage_execution_snapshot(execution["execution_id"], owner=OWNER)
    assert failed["state"] == "failed"
    assert failed["counts"]["work_items"]["completed"] == 1
    assert failed["counts"]["work_items"]["failed"] == 1
    assert failed["reconciliation"]["exact"] is True
    assert failed["output_manifest_id"] is None

    replay = isolated_store.ensure_synchronous_stage_execution(
        scan_id=sid, stage="release", input_ids=["a.pdf", "b.pdf"],
        input_snapshot_id="remediate-snapshot", request_fingerprint=fingerprint)
    assert replay["execution_id"] == execution["execution_id"] and replay["reused"] is True
    waiting = isolated_store.stage_execution_snapshot(execution["execution_id"], owner=OWNER)
    assert waiting["counts"]["work_items"]["completed"] == 1
    assert waiting["counts"]["work_items"]["queued"] == 1
    isolated_store.finish_synchronous_stage_item(
        execution["execution_id"], "b.pdf", outcome="completed", result={"file": "b.pdf"})
    succeeded = isolated_store.stage_execution_snapshot(execution["execution_id"], owner=OWNER)
    assert succeeded["state"] == "succeeded"
    assert succeeded["counts"]["work_items"]["completed"] == 2
    assert isolated_store.get_stage_output_manifest(
        succeeded["output_manifest_id"], owner=OWNER)["item_count"] == 2


class _RouteStore:
    def __init__(self, source):
        self.source = source
        self.events = []
        self.document = None

    def get_scan(self, sid, owner=None):
        return {"run": {"id": sid, "source": self.source, "owner_email": OWNER},
                "files": [{"file": "one.pdf", "compliant": 1, "remediated_at": "now"}]}

    def get_file_record(self, sid, filename):
        return {"file": filename, "compliant": 1, "remediated_at": "now",
                "drive_file_id": "source-1", "source_relative_path": "Policies/one.pdf",
                "corrected_sha256": "sha256-content"}

    def ensure_release_execution(self, *args, **kwargs):
        return {"id": "release-1", "created_at": "2026-09-05T10:00:00+00:00",
                "folder_name": "Release"}

    def current_stage_output_manifest(self, *args):
        return None

    def ensure_synchronous_stage_execution(self, **kwargs):
        self.events.append("stage")
        return {"execution_id": "execution-1", "items": {"one.pdf": "work-1"},
                "reused": False}

    def finish_synchronous_stage_item(self, *args, **kwargs):
        self.events.append(("finish", kwargs["outcome"]))

    def get_release_document(self, *args):
        return self.document

    def record_release_document(self, release_id, owner, result):
        self.events.append("document")
        self.document = dict(result)

    def release_finding_lineage(self, *args):
        return {"findings": [{"finding_id": "finding-1"}]}

    def record_side_effect_receipt(self, **kwargs):
        self.events.append(("receipt", kwargs))
        return {"effect_id": "effect-1"}

    def record_publish(self, *args, **kwargs):
        self.events.append("publish")
        return "2026-09-05T10:01:00+00:00"

    def release_status(self, *args):
        published = int(bool(self.document and self.document["status"] == "published"))
        return {"folder_name": "Release", "roots": [], "documents_total": 1,
                "published": published, "failed": 0, "remaining": 1 - published}


def _request(headers=None):
    return SimpleNamespace(state=SimpleNamespace(user_email=OWNER), headers=headers or {})


def test_local_release_verifies_blob_and_records_receipt_before_publication(monkeypatch):
    import core
    import publish
    from routes import scans

    store = _RouteStore("local")
    monkeypatch.setattr(core, "store", store)
    monkeypatch.setattr(publish, "remediated_content_digest", lambda *args: "sha256-content")
    response = scans.publish_files("scan-1", _request(), {"files": ["one.pdf"]})

    assert response["batch_id"] == "execution-1"
    assert [event if isinstance(event, str) else event[0] for event in store.events] == [
        "stage", "receipt", "publish", "document", "finish"]
    receipt = store.events[1][1]
    assert receipt["effect_type"] == "blob.release"
    assert receipt["work_item_id"] == "work-1"
    assert receipt["content_digest"] == "sha256-content"
    assert receipt["receipt"]["finding_lineage"]["findings"][0]["finding_id"] == "finding-1"


def test_local_release_does_not_publish_a_missing_blob(monkeypatch):
    import core
    import publish
    from routes import scans

    store = _RouteStore("local")
    monkeypatch.setattr(core, "store", store)
    monkeypatch.setattr(publish, "remediated_content_digest", lambda *args: None)

    response = scans.publish_files("scan-1", _request(), {"files": ["one.pdf"]})

    assert response["published"][0]["status"] == "failed"
    assert response["published"][0]["failure_category"] == "provider_write_failed"
    labels = [event if isinstance(event, str) else event[0] for event in store.events]
    assert "receipt" not in labels and "publish" not in labels
    assert labels[-2:] == ["document", "finish"]


def test_drive_release_reserves_before_provider_and_finalizes_before_document(monkeypatch):
    import core
    import handlers
    import publish
    from routes import scans

    store = _RouteStore("drive")
    store.root = None
    store.get_release_root = lambda *args: store.root
    store.record_release_root = lambda *args: setattr(store, "root", {
        "folder_id": "root-1", "folder_name": "Release", "folder_url": "url"}) or store.root
    store.reserve_side_effect = lambda **kwargs: store.events.append(("reserve", kwargs)) or {
        "effect_id": "effect-1", "reservation_token": "token-1", "status": "reserved",
        "acquired": True, "reused": False}
    store.finalize_side_effect = lambda *args: store.events.append(("finalize", args)) or {}
    monkeypatch.setattr(core, "store", store)
    monkeypatch.setattr(handlers, "_drive_client", lambda token: object())
    monkeypatch.setattr(publish, "remediated_content_digest", lambda *args: "sha256-content")
    monkeypatch.setattr(publish, "ensure_published_folder", lambda *args, **kwargs: {
        "id": "root-1", "name": "Release", "url": "url"})
    monkeypatch.setattr(publish, "archive_copy_publish",
                        lambda *args, **kwargs: store.events.append("provider") or {
                            "id": "copy-1", "url": "copy-url", "checksum": "md5-copy",
                            "verified": True, "created": True})

    scans.publish_files("scan-1", _request({"x-drive-token": "token"}),
                        {"files": ["one.pdf"]})

    labels = [event if isinstance(event, str) else event[0] for event in store.events]
    assert labels.index("reserve") < labels.index("provider") < labels.index("finalize")
    assert labels.index("finalize") < labels.index("publish") < labels.index("document")
    reservation = next(event[1] for event in store.events if isinstance(event, tuple)
                       and event[0] == "reserve")
    assert reservation["effect_type"] == "drive.publish"
    assert reservation["destination"] == "google:me:release-1:Policies/one.pdf"
    assert reservation["work_item_id"] == "work-1"


def test_drive_release_reuses_completed_receipt_without_provider_write(monkeypatch):
    import core
    import handlers
    import publish
    from routes import scans

    store = _RouteStore("drive")
    store.get_release_root = lambda *args: {
        "folder_id": "root-1", "folder_name": "Release", "folder_url": "url"}
    store.reserve_side_effect = lambda **kwargs: {
        "effect_id": "effect-1", "status": "completed", "acquired": False, "reused": True,
        "receipt": {"provider_id": "copy-1", "url": "copy-url", "checksum": "md5-copy",
                    "created": False, "verified": True}}
    store.finalize_side_effect = lambda *args: (_ for _ in ()).throw(
        AssertionError("a completed receipt must not be finalized twice"))
    monkeypatch.setattr(core, "store", store)
    monkeypatch.setattr(handlers, "_drive_client", lambda token: object())
    monkeypatch.setattr(publish, "remediated_content_digest", lambda *args: "sha256-content")
    monkeypatch.setattr(publish, "archive_copy_publish", lambda *args, **kwargs: (
        _ for _ in ()).throw(AssertionError("a completed receipt must prevent provider I/O")))

    response = scans.publish_files(
        "scan-1", _request({"x-drive-token": "token"}), {"files": ["one.pdf"]})

    assert response["published"][0]["status"] == "published"
    assert response["published"][0]["released_document_id"] == "copy-1"
    assert store.events[-3:] == ["publish", "document", ("finish", "completed")]


def test_drive_release_keeps_uncertain_provider_outcome_queued(monkeypatch):
    import core
    import handlers
    import publish
    from routes import scans

    store = _RouteStore("drive")
    store.get_release_root = lambda *args: {
        "folder_id": "root-1", "folder_name": "Release", "folder_url": "url"}
    store.reserve_side_effect = lambda **kwargs: store.events.append(("reserve", kwargs)) or {
        "effect_id": "effect-1", "reservation_token": "token-1", "status": "reserved",
        "acquired": True, "reused": False}
    monkeypatch.setattr(core, "store", store)
    monkeypatch.setattr(handlers, "_drive_client", lambda token: object())
    monkeypatch.setattr(publish, "remediated_content_digest", lambda *args: "sha256-content")
    monkeypatch.setattr(publish, "archive_copy_publish", lambda *args, **kwargs: (
        _ for _ in ()).throw(IOError("connection ended after request")))

    response = scans.publish_files(
        "scan-1", _request({"x-drive-token": "token"}), {"files": ["one.pdf"]})

    assert response["published"][0]["status"] == "queued"
    assert "uncertain" in response["published"][0]["explanation"]
    assert not any(isinstance(event, tuple) and event[0] == "finish"
                   for event in store.events)
