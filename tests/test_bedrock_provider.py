"""AWS Bedrock vision adapter — unit and structural tests.

Covers BedrockVisionProvider (happy path, SigV4 client construction, payload shape, error
branches), activation_readiness, _adapter_for, and the Settings.jsx ADAPTER_READY guard.
boto3 is not installed in this environment, so every test that exercises generate() patches
sys.modules["boto3"] before the lazy import inside generate() runs.
"""
from __future__ import annotations
import json
import sys
import types
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))
import providers  # noqa: E402


# ── helpers ───────────────────────────────────────────────────────────────────────────────────────

def _body_bytes(text="A black square on a white background.", input_tokens=100, output_tokens=20):
    return json.dumps({
        "content": [{"type": "text", "text": text}],
        "stop_reason": "end_turn",
        "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
    }).encode()


def _fake_boto3_module(mock_client=None):
    """Build a minimal fake boto3 module that sys.modules can host."""
    mod = types.ModuleType("boto3")
    mod.client = MagicMock(return_value=mock_client or MagicMock())
    return mod


def _inject_boto3(monkeypatch, mock_client):
    """Patch sys.modules so that `import boto3` inside generate() returns our fake."""
    fake = _fake_boto3_module(mock_client)
    monkeypatch.setitem(sys.modules, "boto3", fake)
    # botocore.exceptions is also imported; stub it out
    botocore = types.ModuleType("botocore")
    botocore.exceptions = types.ModuleType("botocore.exceptions")
    monkeypatch.setitem(sys.modules, "botocore", botocore)
    monkeypatch.setitem(sys.modules, "botocore.exceptions", botocore.exceptions)
    return fake


def _mock_client_ok(text="A black square on a white background.",
                    input_tokens=100, output_tokens=20):
    client = MagicMock()
    client.invoke_model.return_value = {"body": BytesIO(_body_bytes(text, input_tokens,
                                                                     output_tokens))}
    return client


# ── 1. BedrockVisionProvider unit tests ──────────────────────────────────────────────────────────

def test_bedrock_invoke_model_called_with_correct_modelid(monkeypatch):
    mock_client = _mock_client_ok()
    _inject_boto3(monkeypatch, mock_client)
    p = providers.BedrockVisionProvider("AKID", "SECRET", region="us-east-1",
                                        model="anthropic.claude-3-5-sonnet-20241022-v2:0")
    res = p.generate("describe", b"IMGBYTES")
    assert res["ok"] is True
    mock_client.invoke_model.assert_called_once()
    call_kwargs = mock_client.invoke_model.call_args.kwargs
    assert call_kwargs["modelId"] == "anthropic.claude-3-5-sonnet-20241022-v2:0"
    assert call_kwargs["contentType"] == "application/json"
    assert call_kwargs["accept"] == "application/json"


def test_bedrock_boto3_client_constructed_with_region_and_credentials(monkeypatch):
    mock_client = _mock_client_ok()
    fake_boto3 = _inject_boto3(monkeypatch, mock_client)
    seen = {}
    original = fake_boto3.client

    def capture(service, region_name=None, aws_access_key_id=None,
                 aws_secret_access_key=None, **k):
        seen["service"] = service
        seen["region"] = region_name
        seen["key_id"] = aws_access_key_id
        seen["secret_set"] = bool(aws_secret_access_key)
        return mock_client

    fake_boto3.client = capture
    p = providers.BedrockVisionProvider("MY_KEY_ID", "MY_SECRET", region="eu-west-1",
                                        model="anthropic.claude-3-haiku-20240307-v1:0")
    p.generate("x", b"IMG")
    assert seen["service"] == "bedrock-runtime"
    assert seen["region"] == "eu-west-1"
    assert seen["key_id"] == "MY_KEY_ID"
    assert seen["secret_set"] is True


def test_bedrock_secret_never_in_result(monkeypatch):
    _inject_boto3(monkeypatch, _mock_client_ok())
    p = providers.BedrockVisionProvider("AKID", "SUPER_SECRET_KEY", region="us-east-1",
                                        model="anthropic.claude-3-5-sonnet-20241022-v2:0")
    res = p.generate("x", b"IMG")
    assert "SUPER_SECRET_KEY" not in str(res)


def test_bedrock_zone_is_always_cloud():
    p = providers.BedrockVisionProvider("k", "s", region="us-west-2",
                                        model="anthropic.claude-3-haiku-20240307-v1:0")
    assert p.zone == "cloud"


def test_bedrock_image_sent_as_base64_in_anthropic_format(monkeypatch):
    import base64
    captured_body = {}
    mock_client = MagicMock()

    def fake_invoke(**kwargs):
        captured_body["data"] = json.loads(kwargs["body"])
        return {"body": BytesIO(_body_bytes("ok"))}

    mock_client.invoke_model = fake_invoke
    _inject_boto3(monkeypatch, mock_client)
    raw = b"\x89PNG fake image bytes"
    p = providers.BedrockVisionProvider("k", "s", region="us-east-1",
                                        model="anthropic.claude-3-haiku-20240307-v1:0")
    p.generate("describe", raw)
    body = captured_body["data"]
    assert body["anthropic_version"] == "bedrock-2023-05-31"
    msgs = body["messages"]
    assert len(msgs) == 1 and msgs[0]["role"] == "user"
    content = msgs[0]["content"]
    img_block = next(b for b in content if b.get("type") == "image")
    assert img_block["source"]["type"] == "base64"
    assert img_block["source"]["media_type"] == "image/png"
    assert img_block["source"]["data"] == base64.b64encode(raw).decode("ascii")


def test_bedrock_text_extracted_from_response(monkeypatch):
    _inject_boto3(monkeypatch, _mock_client_ok("Mostly white with a small black square."))
    p = providers.BedrockVisionProvider("k", "s", region="us-east-1",
                                        model="anthropic.claude-3-haiku-20240307-v1:0")
    res = p.generate("describe", b"IMG")
    assert res["ok"] is True
    assert res["text"] == "Mostly white with a small black square."
    assert res["provider"] == "bedrock"


def test_bedrock_exception_returns_ok_false(monkeypatch):
    mock_client = MagicMock()
    mock_client.invoke_model.side_effect = Exception("ClientError: AccessDeniedException")
    _inject_boto3(monkeypatch, mock_client)
    p = providers.BedrockVisionProvider("k", "s", region="us-east-1",
                                        model="anthropic.claude-3-haiku-20240307-v1:0")
    res = p.generate("x", b"IMG")
    assert res["ok"] is False


def test_bedrock_empty_content_returns_reason_empty(monkeypatch):
    empty_bytes = json.dumps({
        "content": [{"type": "text", "text": ""}],
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 5, "output_tokens": 0},
    }).encode()
    mock_client = MagicMock()
    mock_client.invoke_model.return_value = {"body": BytesIO(empty_bytes)}
    _inject_boto3(monkeypatch, mock_client)
    p = providers.BedrockVisionProvider("k", "s", region="us-east-1",
                                        model="anthropic.claude-3-haiku-20240307-v1:0")
    res = p.generate("x", b"IMG")
    assert res["ok"] is False
    assert res["reason"] == providers.REASON_EMPTY


def test_bedrock_cost_computed_from_usage(monkeypatch):
    _inject_boto3(monkeypatch, _mock_client_ok(input_tokens=1000, output_tokens=100))
    p = providers.BedrockVisionProvider("k", "s", region="us-east-1",
                                        model="anthropic.claude-3-5-sonnet-20241022-v2:0")
    res = p.generate("x", b"IMG")
    assert res["ok"] is True
    assert res["prompt_tokens"] == 1000
    assert res["completion_tokens"] == 100


# ── 2. activation_readiness for bedrock ──────────────────────────────────────────────────────────

def test_bedrock_missing_model_is_not_ready():
    r = providers.activation_readiness("bedrock", {
        "region": "us-east-1", "aws_access_key_id": "AKID", "key_secret_ref": "AWS_SECRET"})
    assert r["ready"] is False
    assert "model" in r["missing"]


def test_bedrock_missing_region_is_not_ready():
    r = providers.activation_readiness("bedrock", {
        "model": "m", "aws_access_key_id": "AKID", "key_secret_ref": "AWS_SECRET"})
    assert r["ready"] is False
    assert "region" in r["missing"]


def test_bedrock_missing_access_key_id_is_not_ready():
    r = providers.activation_readiness("bedrock", {
        "model": "m", "region": "us-east-1", "key_secret_ref": "AWS_SECRET"})
    assert r["ready"] is False
    assert "aws_access_key_id" in r["missing"]


def test_bedrock_missing_key_ref_is_not_ready():
    r = providers.activation_readiness("bedrock", {
        "model": "m", "region": "us-east-1", "aws_access_key_id": "AKID"})
    assert r["ready"] is False
    assert "key_secret_ref" in r["missing"]


def test_bedrock_ready_when_all_fields_and_secret_present(monkeypatch):
    monkeypatch.setenv("AWS_SECRET", "my-secret-value")
    r = providers.activation_readiness("bedrock", {
        "model": "anthropic.claude-3-haiku-20240307-v1:0",
        "region": "us-east-1", "aws_access_key_id": "AKID", "key_secret_ref": "AWS_SECRET"})
    assert r["ready"] is True
    assert r["missing"] == []
    assert r["secret_resolves"] is True


def test_bedrock_not_ready_when_secret_absent(monkeypatch):
    monkeypatch.delenv("AWS_SECRET", raising=False)
    r = providers.activation_readiness("bedrock", {
        "model": "m", "region": "us-east-1", "aws_access_key_id": "AKID",
        "key_secret_ref": "AWS_SECRET"})
    assert r["ready"] is False
    assert r["missing"] == []   # ops's job, not admin's


# ── 3. _adapter_for for bedrock ───────────────────────────────────────────────────────────────────

def test_adapter_for_bedrock_returns_instance_when_complete(monkeypatch):
    monkeypatch.setenv("AWS_SECRET", "val")
    adapter = providers._adapter_for("bedrock", {
        "model": "anthropic.claude-3-haiku-20240307-v1:0",
        "region": "us-east-1", "aws_access_key_id": "AKID", "key_secret_ref": "AWS_SECRET"})
    assert isinstance(adapter, providers.BedrockVisionProvider)
    assert adapter.model == "anthropic.claude-3-haiku-20240307-v1:0"
    assert adapter.region == "us-east-1"


def test_adapter_for_bedrock_none_without_secret(monkeypatch):
    monkeypatch.delenv("AWS_SECRET", raising=False)
    adapter = providers._adapter_for("bedrock", {
        "model": "m", "region": "us-east-1", "aws_access_key_id": "AKID",
        "key_secret_ref": "AWS_SECRET"})
    assert adapter is None


def test_adapter_for_bedrock_none_without_region(monkeypatch):
    monkeypatch.setenv("AWS_SECRET", "val")
    adapter = providers._adapter_for("bedrock", {
        "model": "m", "aws_access_key_id": "AKID", "key_secret_ref": "AWS_SECRET"})
    assert adapter is None


def test_adapter_for_bedrock_none_without_access_key_id(monkeypatch):
    monkeypatch.setenv("AWS_SECRET", "val")
    adapter = providers._adapter_for("bedrock", {
        "model": "m", "region": "us-east-1", "key_secret_ref": "AWS_SECRET"})
    assert adapter is None


# ── 4. Settings.jsx structural guard ─────────────────────────────────────────────────────────────

def test_settings_jsx_adapter_ready_includes_bedrock():
    import re
    jsx = (Path(__file__).resolve().parent.parent / "frontend" / "src" / "Settings.jsx").read_text()
    m = re.search(r"ADAPTER_READY\s*=\s*new Set\(\[([^\]]+)\]\)", jsx)
    assert m, "Could not find ADAPTER_READY set in Settings.jsx"
    names = {n.strip().strip("'\"") for n in m.group(1).split(",")}
    assert "bedrock" in names, f"'bedrock' not in ADAPTER_READY; found: {names}"
