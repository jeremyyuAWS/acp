"""ADR 0020 — the source-bytes blob cache seam.

A scan's download loop stashes each file's bytes in the blob 'sources' container as it
downloads them, keyed by content checksum when one was known before download (Drive's
md5Checksum) — so a LATER, different scan that re-encounters the same content is a cache
hit, not just a retry of the same scan. Without a pre-download checksum (SharePoint, local),
the key falls back to {owner}/{scan_id}/{filename} — a same-scan-retry benefit only. A cache
failure (or no blob configured) must never fail a scan — every miss falls back to the
ordinary download path unchanged.

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

    def download_blob(self, **kwargs):
        # Accepts the transport budget download_source passes (see tests/test_blob_read_timeout.py)
        # and asserts it, rather than absorbing whatever it is handed. THE SWALLOW MAKES THIS
        # MATTER: download_source turns any exception into None, which the caller reads as a plain
        # cache miss — so a kwarg the real client rejected would silently disable the source cache
        # in production and look exactly like "nothing was ever cached". A strict double is the
        # only place that difference is visible.
        assert kwargs.get("read_timeout"), "the cached-source read must carry a read timeout"
        assert kwargs.get("connection_timeout"), "the cached-source read must carry a connect timeout"
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


# ── checksum-keyed cache: the cross-scan hit ────────────────────────────────────

def test_checksum_keyed_write_is_found_by_a_different_scan(fake_blob):
    # The whole point of re-keying: scan1 caches "deck.pptx" under its content checksum;
    # scan2, downloading a file with the SAME checksum under a DIFFERENT name, hits it.
    fake_blob.containers.add("sources")
    url = blob.upload_source("a@x.io", "scan1", "deck.pptx", b"PK-bytes", checksum="abc123")
    assert url and url.endswith("/sources/a@x.io/abc123")
    assert blob.download_source("a@x.io", "scan2", "renamed-deck.pptx", checksum="abc123") == b"PK-bytes"
    # A read for the SAME scan/name but the WRONG checksum is still a miss — the checksum,
    # not the scan_id/filename, is what decides identity once one is given.
    assert blob.download_source("a@x.io", "scan1", "deck.pptx", checksum="different") is None


def test_no_checksum_falls_back_to_scan_id_keying_no_cross_scan_bleed(fake_blob):
    # Unchanged from ADR 0020 §1: SharePoint/local (checksum=None) still key by scan_id, so
    # two scans of an unrelated file never collide just for lacking a checksum.
    fake_blob.containers.add("sources")
    blob.upload_source("a@x.io", "scan1", "deck.pptx", b"PK-bytes")
    assert blob.download_source("a@x.io", "scan1", "deck.pptx") == b"PK-bytes"
    assert blob.download_source("a@x.io", "scan2", "deck.pptx") is None


def test_checksum_and_scan_id_keys_never_collide(fake_blob):
    # A checksum string can never equal a real scan_id/filename path (the key shapes are
    # disjoint: one segment vs two), but pin it down explicitly rather than assuming.
    fake_blob.containers.add("sources")
    blob.upload_source("a@x.io", "scan1", "deck.pptx", b"scan-id-keyed")
    blob.upload_source("a@x.io", "scan1", "deck.pptx", b"checksum-keyed", checksum="abc123")
    assert blob.download_source("a@x.io", "scan1", "deck.pptx") == b"scan-id-keyed"
    assert blob.download_source("a@x.io", "scan1", "deck.pptx", checksum="abc123") == b"checksum-keyed"


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


def test_cache_source_bytes_with_checksum_is_found_by_read_from_a_different_scan(
        tmp_path, monkeypatch, fake_blob):
    fake_blob.containers.add("sources")
    monkeypatch.setattr(blob, "enabled", lambda: True)
    (tmp_path / "report.docx").write_bytes(b"DOCX")
    scanner.cache_source_bytes(tmp_path, "report.docx", "scan1", "u@x.io", checksum="ck1")
    assert fake_blob.store[("sources", "u@x.io/ck1")] == b"DOCX"
    assert scanner.read_cached_source("scan2", "report.docx", "u@x.io", checksum="ck1") == b"DOCX"


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


# ── scanner.read_cached_source: the stage 1 read side ───────────────────────────

def test_read_cached_source_returns_a_prior_cache_hit(fake_blob):
    # fake_blob already sets blob._ENABLED = True for the duration of this test.
    fake_blob.containers.add("sources")
    blob.upload_source("u@x.io", "scan1", "deck.pptx", b"PK-bytes")
    assert scanner.read_cached_source("scan1", "deck.pptx", "u@x.io") == b"PK-bytes"


def test_read_cached_source_is_none_on_a_miss(fake_blob):
    fake_blob.containers.add("sources")
    assert scanner.read_cached_source("scan1", "never-cached.docx", "u@x.io") is None


def test_read_cached_source_is_none_when_blob_unconfigured():
    # No ACP_BLOB_ACCOUNT (the default in this suite) → miss, never raises.
    assert scanner.read_cached_source("scan1", "f.docx", "u@x.io") is None


def test_read_cached_source_never_raises(monkeypatch, fake_blob):
    monkeypatch.setattr(blob, "enabled", lambda: True)
    monkeypatch.setattr(blob, "download_source",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    assert scanner.read_cached_source("scan1", "f.docx", "u@x.io") is None


# ── wiring: BOTH download paths write AND read the cache, checksum included ─────

def test_both_scan_paths_cache_after_download_with_checksum():
    api = Path(__file__).resolve().parent.parent / "api"
    scan_src = (api / "scanner.py").read_text()
    hand_src = (api / "handlers.py").read_text()
    # monolithic read loop (run_scan) and the fan-out per-file body both call the helper
    # immediately after _download, passing the item's pre-download checksum through so a
    # cache write can be found by a LATER, different scan — the ADR's 'open once' seam has
    # no uncovered path.
    assert 'cache_source_bytes(tmp, it["name"], scan_id, user' in scan_src
    assert 'checksum=it.get("checksum")' in scan_src
    assert "cache_source_bytes(tmp, name, scan_id, user, checksum=checksum)" in hand_src


def test_both_scan_paths_check_the_cache_before_download():
    api = Path(__file__).resolve().parent.parent / "api"
    scan_src = (api / "scanner.py").read_text()
    hand_src = (api / "handlers.py").read_text()
    # Both download sites now try read_cached_source (with the item's checksum) before
    # calling _download, so an unchanged file is a cache hit across scans, not just within one.
    read_call = 'read_cached_source(scan_id, it["name"], user, checksum=it.get("checksum"))'
    assert read_call in scan_src
    assert scan_src.index(read_call) < scan_src.index('_download(it, tmp, svc, sp_token=sp_token)')
    read_call_h = "read_cached_source(scan_id, name, user, checksum=checksum)"
    assert read_call_h in hand_src
    assert hand_src.index(read_call_h) < hand_src.index("_download(it, tmp, svc, sp_token=toks.get(\"sp\"))")
