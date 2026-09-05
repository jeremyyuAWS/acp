"""Remediation must look under the key ASSESS ACTUALLY WROTE.

Reading the source bytes instead of re-downloading them (the SharePoint fix) is only worth
anything if the read reaches the write. It did not, and the reason is a checksum that goes
missing between the two halves:

  * Assess caches through `scanner.cache_source_bytes(..., checksum=it.get("checksum"))`, and
    a SharePoint listing has carried `quickXorHash` since #963 (2026-08-29). So the bytes land
    under the CHECKSUM key, `{owner}/{checksum}`.
  * The remediate route passes `checksum=f.get("checksum")` off `store.get_scan`'s file rows —
    and that SELECT does not return a checksum column at all. `file_records.checksum` is NULL
    besides: the scan report's per-file rows carry no checksum for `save_scan` to write. The
    value only ever exists in `scan_inventory.checksum`.

So the job asked for `{owner}/{scan_id}/{filename}`, the bytes were at `{owner}/{checksum}`,
and every SharePoint document missed. Before the source-dispatch fix that miss fell through to
the Drive client and reported a missing Drive token; after it, the miss is honest but the
documents still do not remediate. Both are the same broken lookup.

These tests run the REAL key logic in `blob._source_key` against a fake Azure client, so the
write and the read have to agree the way they do in production — a stubbed `read_cached_source`
would have agreed with itself and proved nothing.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

OWNER = "demo"          # what _owner(request) resolves to without an auth header
DOC = "policy.docx"
QUICKXOR = "quickxor-6c2f1a"
SCAN = "8b83e9e1"


class _FakeBlobClient:
    def __init__(self, store, key):
        self._store, self._key = store, key

    def upload_blob(self, data, overwrite=False, content_settings=None):
        self._store[self._key] = data

    def download_blob(self, **kwargs):
        # The read must arrive with its transport budget — see tests/test_blob_read_timeout.py.
        # Asserted here rather than merely tolerated: a fake that quietly accepted anything would
        # keep passing if the timeouts were dropped, and this is the call they exist to bound.
        assert kwargs.get("read_timeout"), "the cached-source read must carry a read timeout"
        assert kwargs.get("connection_timeout"), "the cached-source read must carry a connect timeout"
        if self._key not in self._store:
            raise KeyError(self._key)
        payload = self._store[self._key]
        return type("_D", (), {"readall": staticmethod(lambda: payload)})()

    @property
    def url(self):
        return f"https://fake/{self._key}"


class _FakeService:
    """Just enough Azure surface for upload_source/download_source, keyed by the real key."""

    def __init__(self):
        self.blobs: dict[str, bytes] = {}

    def get_blob_client(self, container, blob):
        return _FakeBlobClient(self.blobs, f"{container}/{blob}")

    def create_container(self, name):
        pass


@pytest.fixture()
def cache(monkeypatch):
    import blob
    svc = _FakeService()
    monkeypatch.setattr(blob, "_ENABLED", True)
    monkeypatch.setattr(blob, "_service_client", lambda: svc)
    return svc


@pytest.fixture
def client(monkeypatch, isolated_store):
    import core
    monkeypatch.setattr(core, "store", isolated_store)
    from fastapi.testclient import TestClient
    from app import app
    return TestClient(app)


def _sharepoint_scan(store):
    """A SharePoint scan as Assess leaves it: an inventory row carrying the quickXorHash, and a
    file record that does not (the report has no checksum field to write)."""
    store.save_scan({
        "_scan_id": SCAN, "started_at": "2026-09-04T00:00:00Z",
        "completed_at": "2026-09-04T00:01:00Z", "source": "sharepoint", "owner": OWNER,
        "rubric": {"name": "wcag-aa", "hash": "h"},
        "summary": {"files": 1, "certifiable": 0, "uncertain": 1, "error": 0, "avg_score": 50},
        "files": [{"file": DOC, "engine": "office", "status": "uncertain", "score": 50,
                   "compliant": 0, "skipped_rules": 0,
                   "issues": [{"ruleId": "DOC_TITLE", "wcag": "2.4.2", "severity": "SERIOUS"}]}],
    })
    store.add_inventory(SCAN, [{"file": DOC, "checksum": QUICKXOR, "owner": OWNER,
                                "size_kb": 12, "mime": "application/vnd.openxml"}])


def _assess_caches_the_bytes(payload=b"the-original-sharepoint-bytes", tmp_path=None):
    """Exactly what run_scan does after a SharePoint download."""
    import scanner
    tmp_path.joinpath(DOC).write_bytes(payload)
    scanner.cache_source_bytes(tmp_path, DOC, SCAN, OWNER, checksum=QUICKXOR)


def test_the_bytes_assess_cached_are_the_bytes_remediation_reads(client, isolated_store,
                                                                 cache, tmp_path, monkeypatch):
    """The whole chain: Assess writes, the route enqueues, the handler reads.

    This is the test that would have caught the real scan still failing after the Drive-routing
    fix — nothing else asserts that the two halves choose the same key.
    """
    import handlers
    import remediate_office

    _sharepoint_scan(isolated_store)
    _assess_caches_the_bytes(tmp_path=tmp_path)
    assert cache.blobs, "the fixture must have cached something, or this proves nothing"

    r = client.post(f"/scans/{SCAN}/remediate", json={})
    assert r.status_code == 200 and r.json()["enqueued"] == 1
    payload = isolated_store.get_job(r.json()["job_ids"][0])["payload"]

    monkeypatch.setattr(handlers.core.store, "is_shadowed_output", lambda sid, f: False)
    monkeypatch.setattr(handlers.core.store, "list_auto_fail_rules", lambda sid, f: [])
    monkeypatch.setattr(handlers, "_phase", lambda *a, **k: None)
    monkeypatch.setattr(handlers, "_propose_text_findings", lambda *a, **k: None)
    monkeypatch.setattr(handlers, "_propose_form_fields", lambda *a, **k: None)
    monkeypatch.setattr(handlers, "_remediation_scope", lambda *a, **kw: None)
    monkeypatch.setattr(handlers, "_drive_client", lambda tok: pytest.fail(
        "a SharePoint job must never build a Drive client"))

    class _Reached(Exception):
        pass

    def _remediate(path, **kwargs):
        assert path.read_bytes() == b"the-original-sharepoint-bytes"
        raise _Reached()

    monkeypatch.setattr(remediate_office, "remediate_office", _remediate)

    with pytest.raises(_Reached):
        handlers._remediate_file(payload, {})


def test_the_job_carries_the_checksum_assess_keyed_the_cache_with(client, isolated_store, cache,
                                                                  tmp_path):
    """The missing link, asserted directly so a regression names itself.

    `get_scan`'s file rows have no checksum column and `file_records.checksum` is NULL for every
    scan, so the route has to read `scan_inventory` — the only place the value Assess used
    actually lives.
    """
    _sharepoint_scan(isolated_store)

    r = client.post(f"/scans/{SCAN}/remediate", json={})
    payload = isolated_store.get_job(r.json()["job_ids"][0])["payload"]
    assert payload["checksum"] == QUICKXOR, (
        "the job must carry the source checksum, or it looks under a key nothing wrote")


def test_a_scan_with_no_recorded_checksum_still_finds_its_bytes(client, isolated_store, cache,
                                                                tmp_path, monkeypatch):
    """The other key shape, which must keep working.

    A SharePoint scan assessed before quickXorHash was collected (or any source whose listing
    carries no hash) cached under {owner}/{scan_id}/{filename}. Both shapes are live in the same
    estate, so the read tries the checksum key and then this one.
    """
    import scanner

    _sharepoint_scan(isolated_store)
    isolated_store.add_inventory(SCAN, [{"file": DOC, "checksum": None, "owner": OWNER}])
    tmp_path.joinpath(DOC).write_bytes(b"scan-keyed-bytes")
    scanner.cache_source_bytes(tmp_path, DOC, SCAN, OWNER, checksum=None)

    r = client.post(f"/scans/{SCAN}/remediate", json={})
    payload = isolated_store.get_job(r.json()["job_ids"][0])["payload"]
    assert scanner.read_cached_source(SCAN, DOC, OWNER,
                                      checksum=payload.get("checksum")) == b"scan-keyed-bytes"


def test_a_job_queued_before_the_route_stamped_a_checksum_still_finds_its_bytes(
        isolated_store, cache, tmp_path, monkeypatch):
    """Jobs are DURABLE, and the queue outlives the deploy that fixes the enqueuer.

    Every remediate_file job enqueued before the route learned to read scan_inventory carries
    `checksum: None` in its payload — including the 147 from the incident. Fixing only the
    enqueue side would leave those looking under the scan-keyed shape forever, and they would
    fail with an honest message about a cache that does in fact hold their bytes.
    """
    import handlers
    import remediate_office

    _sharepoint_scan(isolated_store)
    _assess_caches_the_bytes(tmp_path=tmp_path)
    monkeypatch.setattr(handlers.core, "store", isolated_store)
    monkeypatch.setattr(handlers, "_phase", lambda *a, **k: None)
    monkeypatch.setattr(handlers, "_propose_text_findings", lambda *a, **k: None)
    monkeypatch.setattr(handlers, "_propose_form_fields", lambda *a, **k: None)
    monkeypatch.setattr(handlers, "_remediation_scope", lambda *a, **kw: None)
    monkeypatch.setattr(handlers, "_drive_client", lambda tok: pytest.fail(
        "a SharePoint job must never build a Drive client"))

    class _Reached(Exception):
        pass

    def _remediate(path, **kwargs):
        assert path.read_bytes() == b"the-original-sharepoint-bytes"
        raise _Reached()

    monkeypatch.setattr(remediate_office, "remediate_office", _remediate)

    # The payload as the incident's jobs were written: no checksum at all.
    with pytest.raises(_Reached):
        handlers._remediate_file({"scan_id": SCAN, "file": DOC, "source": "sharepoint",
                                  "owner": OWNER, "checksum": None}, {})
