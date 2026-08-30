"""api/workspace_blob.py (ADR 0044) — the Azure Blob module for workspace uploads.

Same testing discipline as tests/test_perf_blobstore.py (api/blob.py's own test file): fake
azure.* modules injected into sys.modules so the module loads without the real package (broken
in this sandbox anyway — see CLAUDE.md's _cffi_backend note), then api-shaped fakes standing in
for the SDK objects it calls. UNVERIFIED against a live Azure account, same caveat as every
other azure-sdk-touching module in this codebase.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))


@pytest.fixture(autouse=True)
def _mock_azure(monkeypatch):
    """Stub the azure SDK so workspace_blob.py loads cleanly without the real package."""
    azure_blob_mod = MagicMock()
    monkeypatch.setitem(sys.modules, "azure", MagicMock())
    monkeypatch.setitem(sys.modules, "azure.storage", MagicMock())
    monkeypatch.setitem(sys.modules, "azure.storage.blob", azure_blob_mod)
    monkeypatch.setitem(sys.modules, "azure.identity", MagicMock())
    return azure_blob_mod


# ── not configured: every public function is a safe no-op ───────────────────

def test_enabled_is_false_without_the_account_env_var():
    import workspace_blob
    assert workspace_blob.enabled() is False


def test_generate_upload_authorization_returns_none_when_not_configured():
    import workspace_blob
    assert workspace_blob.generate_upload_authorization("a@b.c", "ws1", "doc1") is None


def test_get_uploaded_blob_properties_returns_none_when_not_configured():
    import workspace_blob
    assert workspace_blob.get_uploaded_blob_properties("a@b.c", "ws1", "doc1", "v1") is None


def test_download_document_bytes_returns_none_when_not_configured():
    import workspace_blob
    assert workspace_blob.download_document_bytes("a@b.c", "ws1", "doc1", "v1") is None


def test_delete_document_version_returns_false_when_not_configured():
    import workspace_blob
    assert workspace_blob.delete_document_version("a@b.c", "ws1", "doc1", "v1") is False


# ── blob_path: ADR 0044's layout, exactly ───────────────────────────────────

def testblob_path_matches_the_adr_layout():
    import workspace_blob
    path = workspace_blob.blob_path("alice@x.com", "ws1", "doc1", "v1")
    assert path == "workspace/alice@x.com/ws1/doc1/source/v1/original"


def testblob_path_supports_other_kinds():
    import workspace_blob
    path = workspace_blob.blob_path("alice@x.com", "ws1", "doc1", "v1", kind="remediated",
                                     leaf="artifact")
    assert path == "workspace/alice@x.com/ws1/doc1/remediated/v1/artifact"


def testblob_path_falls_back_to_demo_for_no_owner():
    import workspace_blob
    path = workspace_blob.blob_path(None, "ws1", "doc1", "v1")
    assert path.startswith("workspace/demo/")


# ── generate_upload_authorization: configured, happy path ───────────────────

def test_generate_upload_authorization_returns_a_scoped_write_only_sas(monkeypatch, _mock_azure):
    import workspace_blob

    svc = MagicMock()
    udk = MagicMock()
    svc.get_user_delegation_key.return_value = udk
    monkeypatch.setattr(workspace_blob, "_service_client", lambda: svc)
    monkeypatch.setattr(_mock_azure, "generate_blob_sas", lambda **kw: "fake-sas-token")

    result = workspace_blob.generate_upload_authorization("alice@x.com", "ws1", "doc1")

    assert result is not None
    assert result["upload_url"].startswith("https://")
    assert result["upload_url"].endswith("?fake-sas-token")
    assert result["blob_path"] == f"workspace/alice@x.com/ws1/doc1/source/{result['version_id']}/original"
    assert result["version_id"]


def test_generate_upload_authorization_requests_write_and_create_only(monkeypatch, _mock_azure):
    """PRD §9: 'permit upload but not container listing' — no read/list/delete permission is
    ever requested."""
    import workspace_blob

    svc = MagicMock()
    svc.get_user_delegation_key.return_value = MagicMock()
    monkeypatch.setattr(workspace_blob, "_service_client", lambda: svc)
    captured = {}

    def _fake_sas(**kw):
        captured.update(kw)
        return "tok"
    monkeypatch.setattr(_mock_azure, "generate_blob_sas", _fake_sas)

    workspace_blob.generate_upload_authorization("alice@x.com", "ws1", "doc1")

    perm_call = _mock_azure.BlobSasPermissions.call_args
    assert perm_call.kwargs == {"write": True, "create": True}


def test_generate_upload_authorization_expires_quickly_by_default(monkeypatch, _mock_azure):
    import workspace_blob

    svc = MagicMock()
    svc.get_user_delegation_key.return_value = MagicMock()
    monkeypatch.setattr(workspace_blob, "_service_client", lambda: svc)
    monkeypatch.setattr(_mock_azure, "generate_blob_sas", lambda **kw: "tok")

    before = datetime.now(timezone.utc)
    result = workspace_blob.generate_upload_authorization("alice@x.com", "ws1", "doc1")
    expires_at = datetime.fromisoformat(result["expires_at"])

    assert expires_at <= before + timedelta(seconds=workspace_blob._UPLOAD_SAS_TTL_SECONDS + 5)
    assert expires_at > before


def test_two_calls_never_reuse_the_same_version_id_or_path(monkeypatch, _mock_azure):
    """PRD §9: 'prevent overwrite of another object' — holds because a fresh, never-used
    version_id (and therefore a fresh blob path) is minted on every call."""
    import workspace_blob

    svc = MagicMock()
    svc.get_user_delegation_key.return_value = MagicMock()
    monkeypatch.setattr(workspace_blob, "_service_client", lambda: svc)
    monkeypatch.setattr(_mock_azure, "generate_blob_sas", lambda **kw: "tok")

    r1 = workspace_blob.generate_upload_authorization("alice@x.com", "ws1", "doc1")
    r2 = workspace_blob.generate_upload_authorization("alice@x.com", "ws1", "doc1")
    assert r1["version_id"] != r2["version_id"]
    assert r1["blob_path"] != r2["blob_path"]


# ── get_uploaded_blob_properties ─────────────────────────────────────────────

def test_get_uploaded_blob_properties_returns_size_and_md5(monkeypatch):
    import workspace_blob

    props = MagicMock()
    props.size = 1024
    props.content_settings.content_md5 = b"\x01\x02\x03"
    blob_client = MagicMock()
    blob_client.get_blob_properties.return_value = props
    svc = MagicMock()
    svc.get_blob_client.return_value = blob_client
    monkeypatch.setattr(workspace_blob, "_service_client", lambda: svc)

    result = workspace_blob.get_uploaded_blob_properties("alice@x.com", "ws1", "doc1", "v1")
    assert result["size"] == 1024
    assert result["content_md5"]  # base64-encoded, non-empty


def test_get_uploaded_blob_properties_returns_none_when_the_blob_is_missing(monkeypatch):
    import workspace_blob

    blob_client = MagicMock()
    blob_client.get_blob_properties.side_effect = Exception("not found")
    svc = MagicMock()
    svc.get_blob_client.return_value = blob_client
    monkeypatch.setattr(workspace_blob, "_service_client", lambda: svc)

    assert workspace_blob.get_uploaded_blob_properties("alice@x.com", "ws1", "doc1", "v1") is None


def test_get_uploaded_blob_properties_handles_no_content_md5(monkeypatch):
    """A client that didn't set Content-MD5 on upload — must not raise on a None hash."""
    import workspace_blob

    props = MagicMock()
    props.size = 512
    props.content_settings.content_md5 = None
    blob_client = MagicMock()
    blob_client.get_blob_properties.return_value = props
    svc = MagicMock()
    svc.get_blob_client.return_value = blob_client
    monkeypatch.setattr(workspace_blob, "_service_client", lambda: svc)

    result = workspace_blob.get_uploaded_blob_properties("alice@x.com", "ws1", "doc1", "v1")
    assert result == {"size": 512, "content_md5": None}


# ── download_document_bytes / delete_document_version ───────────────────────

def test_download_document_bytes_returns_the_bytes(monkeypatch):
    import workspace_blob

    downloader = MagicMock()
    downloader.readall.return_value = b"pdf bytes"
    blob_client = MagicMock()
    blob_client.download_blob.return_value = downloader
    svc = MagicMock()
    svc.get_blob_client.return_value = blob_client
    monkeypatch.setattr(workspace_blob, "_service_client", lambda: svc)

    assert workspace_blob.download_document_bytes("alice@x.com", "ws1", "doc1", "v1") == b"pdf bytes"


def test_download_document_bytes_returns_none_on_a_missing_blob(monkeypatch):
    import workspace_blob

    blob_client = MagicMock()
    blob_client.download_blob.side_effect = Exception("not found")
    svc = MagicMock()
    svc.get_blob_client.return_value = blob_client
    monkeypatch.setattr(workspace_blob, "_service_client", lambda: svc)

    assert workspace_blob.download_document_bytes("alice@x.com", "ws1", "doc1", "v1") is None


def test_delete_document_version_returns_true_on_success(monkeypatch):
    import workspace_blob

    blob_client = MagicMock()
    svc = MagicMock()
    svc.get_blob_client.return_value = blob_client
    monkeypatch.setattr(workspace_blob, "_service_client", lambda: svc)

    assert workspace_blob.delete_document_version("alice@x.com", "ws1", "doc1", "v1") is True
    blob_client.delete_blob.assert_called_once()


def test_delete_document_version_returns_false_on_failure(monkeypatch):
    import workspace_blob

    blob_client = MagicMock()
    blob_client.delete_blob.side_effect = Exception("gone")
    svc = MagicMock()
    svc.get_blob_client.return_value = blob_client
    monkeypatch.setattr(workspace_blob, "_service_client", lambda: svc)

    assert workspace_blob.delete_document_version("alice@x.com", "ws1", "doc1", "v1") is False
