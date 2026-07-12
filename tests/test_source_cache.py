"""ADR 0020 stage 1 — the source-bytes blob cache seam.

Discover downloads each file once; stage 1 stashes those bytes in the blob 'sources'
container so a later Assess phase can re-read them without a second source download.
This stage is groundwork only: NOTHING reads from the cache yet, a cache failure must
never fail a scan, and without ACP_BLOB_ACCOUNT the whole seam is a silent no-op.

Hermetic: a fake in-memory BlobServiceClient stands in for Azure, so the tests prove the
round-trip, the container/key layout, and the lazy-container retry without any infra.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))
import blob  # noqa: E402
import scanner  # noqa: E402


# ── a minimal fake of the Azure SDK surface blob.py touches ─────────────────────
class _FakeBlob:
    def __init__(self, store, container, path, containers):
        self._store, self._container, self._path, self._containers = store, container, path, containers
        self.url = f"https://fake/{container}/{path}"

    def upload_blob(self, data, overwrite=True, content_settings=None):
        if self._container not in self._containers:
            raise RuntimeError("ContainerNotFound")
        self._store[(self._container, self._path)] = bytes(data)

    def download_blob(self):
        data = self._store.get((self._container, self._path))
        if data is None:
            raise RuntimeError("BlobNotFound")
        class _R:  # noqa: N801 — mimic the SDK's reader
            def __init__(self, b): self._b = b
            def readall(self): return self._b
        return _R(data)


class _FakeService:
    def __init__(self, containers=("remediated", "thumbnails")):
        self.store = {}
        self.containers = set(containers)

    def get_blob_client(self, container, blob):
        return _FakeBlob(self.store, container, blob, self.containers)

    def create_container(self, name):
        self.containers.add(name)


@pytest.fixture
def fake_blob(monkeypatch):
    # The azure SDK is a deploy-only dependency — stub just the symbol blob.py imports
    # inside its functions, so the suite stays hermetic on a dev machine without it.
    import types
    fake_sdk = types.ModuleType("azure.storage.blob")
    fake_sdk.ContentSettings = lambda **k: None
    monkeypatch.setitem(sys.modules, "azure", types.ModuleType("azure"))
    monkeypatch.setitem(sys.modules, "azure.storage", types.ModuleType("azure.storage"))
    monkeypatch.setitem(sys.modules, "azure.storage.blob", fake_sdk)
    svc = _FakeService()
    monkeypatch.setattr(blob, "_service_client", lambda: svc)
    monkeypatch.setattr(blob, "_ENABLED", True)
    return svc


# ── blob.py: round-trip, key layout, lazy container ────────────────────────────

def test_source_bytes_round_trip_under_the_expected_key(fake_blob):
    fake_blob.containers.add("sources")
    url = blob.upload_source("a@x.io", "scan1", "deck.pptx", b"PK-bytes")
    assert url and url.endswith("/sources/a@x.io/scan1/deck.pptx")
    assert blob.download_source("a@x.io", "scan1", "deck.pptx") == b"PK-bytes"
    # a different scan/key is a distinct object — no cross-scan bleed
    assert blob.download_source("a@x.io", "scan2", "deck.pptx") is None


def test_missing_sources_container_is_created_and_the_write_retried(fake_blob):
    assert "sources" not in fake_blob.containers          # fresh account: container absent
    url = blob.upload_source(None, "s1", "f.docx", b"d")
    assert url is not None and "sources" in fake_blob.containers
    assert blob.download_source(None, "s1", "f.docx") == b"d"
    assert ("sources", "demo/s1/f.docx") in fake_blob.store   # owner-less → 'demo', like ADR 0010


def test_unconfigured_blob_is_a_silent_noop():
    # No ACP_BLOB_ACCOUNT (the default in this suite) → every call returns None, never raises.
    assert blob.upload_source("a@x.io", "s", "f", b"d") is None
    assert blob.download_source("a@x.io", "s", "f") is None


# ── scanner.cache_source_bytes: best-effort, never blocking ────────────────────

def test_cache_source_bytes_uploads_the_downloaded_file(tmp_path, monkeypatch, fake_blob):
    fake_blob.containers.add("sources")
    monkeypatch.setattr(blob, "enabled", lambda: True)
    (tmp_path / "report.docx").write_bytes(b"DOCX")
    scanner.cache_source_bytes(tmp_path, "report.docx", "scanX", "u@x.io")
    assert fake_blob.store[("sources", "u@x.io/scanX/report.docx")] == b"DOCX"


def test_cache_source_bytes_never_raises(tmp_path, monkeypatch):
    # blob disabled → no-op
    monkeypatch.setattr(blob, "enabled", lambda: False)
    scanner.cache_source_bytes(tmp_path, "missing.docx", "s", None)
    # blob enabled but the upload explodes → swallowed (a cache failure must not fail a scan)
    monkeypatch.setattr(blob, "enabled", lambda: True)
    monkeypatch.setattr(blob, "upload_source", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    (tmp_path / "f.pdf").write_bytes(b"%PDF")
    scanner.cache_source_bytes(tmp_path, "f.pdf", "s", None)
    # file missing on disk → swallowed too
    scanner.cache_source_bytes(tmp_path, "never-downloaded.pdf", "s", None)


# ── wiring: BOTH download paths feed the cache ──────────────────────────────────

def test_both_scan_paths_cache_after_download():
    api = Path(__file__).resolve().parent.parent / "api"
    scan_src = (api / "scanner.py").read_text()
    hand_src = (api / "handlers.py").read_text()
    # monolithic read loop (run_scan) and the fan-out per-file body both call the helper
    # immediately after _download — the ADR's 'open once' seam has no uncovered path.
    assert "cache_source_bytes(tmp, it[\"name\"], scan_id, user)" in scan_src
    assert "cache_source_bytes(tmp, name, scan_id, user)" in hand_src
