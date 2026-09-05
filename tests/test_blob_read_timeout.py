"""A cached-source read must give the worker slot back.

WHY THIS PATH SPECIFICALLY. `handlers._remediation_source_bytes` reads the ADR 0020 source cache
for every local and SharePoint document, and the production remediate tier runs two slots — so a
request that sits there occupies half the tier while it waits, and the caller cannot tell:
`scanner.read_cached_source` wraps the call in try/except, which sees an exception or a slow
success and has no way to see "still waiting".

THE SDK IS NOT TIMEOUT-FREE, and this test exists because the budget it does have is wrong for
this path rather than absent. Measured on azure-storage-blob 12.24.0: CONNECTION_TIMEOUT=20,
READ_TIMEOUT=60, ExponentialRetry(total_retries=3, initial_backoff=15, increment_base=3) — about
five to six minutes for one stalled read, per chunk request, since readall() streams.

So the assertions are about the values reaching the SDK, at both levels:

  * the client, so every operation inherits them;
  * the download call, because the client is a process-global cached on first use — whichever
    path built it fixed the budget for every later caller — and because the storage
    StorageStreamDownloader replays the kwargs it was given on each chunk request, which is what
    makes the timeout cover a whole streamed read rather than only its first call.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))


class _FakeDownloader:
    def __init__(self, kwargs):
        self.kwargs = kwargs

    def readall(self):
        return b"bytes"


class _FakeBlobClient:
    def __init__(self, seen):
        self._seen = seen

    def download_blob(self, **kwargs):
        self._seen.append(kwargs)
        return _FakeDownloader(kwargs)


class _FakeService:
    def __init__(self):
        self.download_kwargs: list[dict] = []

    def get_blob_client(self, container, blob):
        return _FakeBlobClient(self.download_kwargs)


@pytest.fixture()
def blob_mod(monkeypatch):
    import blob
    monkeypatch.setattr(blob, "_ENABLED", True)
    return blob


def test_the_cached_source_read_carries_a_bounded_timeout(blob_mod, monkeypatch):
    svc = _FakeService()
    monkeypatch.setattr(blob_mod, "_service_client", lambda: svc)

    assert blob_mod.download_source("demo", "s1", "a.docx") == b"bytes"

    assert len(svc.download_kwargs) == 1
    kwargs = svc.download_kwargs[0]
    assert kwargs["connection_timeout"] == blob_mod._CONNECT_TIMEOUT_S
    assert kwargs["read_timeout"] == blob_mod._READ_TIMEOUT_S
    assert 0 < kwargs["read_timeout"] <= 60, (
        "a read on the remediation worker's hot path must be bounded well inside the SDK's own "
        "60s-per-attempt default, which is the budget this exists to tighten")


def test_a_stalled_read_is_a_cache_miss_not_an_exception(blob_mod, monkeypatch):
    """The contract the caller already relies on. scanner.read_cached_source treats any failure
    as a miss, and the remediation dispatch then reports honestly instead of hanging."""
    import socket

    class _TimingOut:
        def get_blob_client(self, container, blob):
            class _C:
                @staticmethod
                def download_blob(**kwargs):
                    raise socket.timeout("read timed out")
            return _C()

    monkeypatch.setattr(blob_mod, "_service_client", lambda: _TimingOut())
    assert blob_mod.download_source("demo", "s1", "a.docx") is None


def test_the_client_is_built_with_the_same_budget(monkeypatch):
    """Every other blob operation inherits it — the read is the hot path, not the only one."""
    import blob

    captured = {}

    class _FakeBSC:
        def __init__(self, account_url, credential=None, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(blob, "_ENABLED", True)
    monkeypatch.setattr(blob, "_ACCOUNT", "acct")
    monkeypatch.setattr(blob, "_client", None)
    monkeypatch.setitem(sys.modules, "azure.identity",
                        type(sys)("azure.identity"))
    sys.modules["azure.identity"].DefaultAzureCredential = lambda *a, **k: object()
    storage = type(sys)("azure.storage.blob")
    storage.BlobServiceClient = _FakeBSC
    monkeypatch.setitem(sys.modules, "azure.storage.blob", storage)

    blob._service_client()
    assert captured["connection_timeout"] == blob._CONNECT_TIMEOUT_S
    assert captured["read_timeout"] == blob._READ_TIMEOUT_S
    assert captured["retry_total"] == blob._RETRY_TOTAL


def test_the_budget_is_tunable_without_a_deploy(monkeypatch):
    """An operator on a slow link widens it with an env var; the defaults are not a ceiling."""
    monkeypatch.setenv("ACP_BLOB_READ_TIMEOUT_S", "120")
    monkeypatch.setenv("ACP_BLOB_CONNECT_TIMEOUT_S", "25")
    import blob
    reloaded = importlib.reload(blob)
    try:
        assert reloaded._READ_TIMEOUT_S == 120
        assert reloaded._CONNECT_TIMEOUT_S == 25
        assert reloaded._timeouts() == {"connection_timeout": 25, "read_timeout": 120}
    finally:
        monkeypatch.delenv("ACP_BLOB_READ_TIMEOUT_S")
        monkeypatch.delenv("ACP_BLOB_CONNECT_TIMEOUT_S")
        importlib.reload(reloaded)   # leave the module as the rest of the suite expects it
