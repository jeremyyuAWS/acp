import json

import pytest

from experiments.document_wide_ai.contracts.v1 import (
    CONTRACT_VERSION,
    AllowedOperation,
    ContractError,
    DocumentContextManifest,
    DocumentFormat,
    Finding,
    Locator,
    parse_edit_response,
    sha256_hex,
)


def _locator(**kw):
    base = dict(
        format=DocumentFormat.PDF,
        page_index=0,
        part_name=None,
        element_ref="structelem:1",
        fingerprint="abc123",
    )
    base.update(kw)
    return Locator(**base)


def test_manifest_round_trips_to_json():
    manifest = DocumentContextManifest(
        contract_version=CONTRACT_VERSION,
        extractor_version="pdf-extractor.v1",
        adapter_version="pdf-adapter.v1",
        document_id="doc-1",
        document_format=DocumentFormat.PDF,
        source_sha256=sha256_hex(b"hello"),
        assessment_revision="rev-1",
        selected_criteria=("1.1.1",),
        findings=(
            Finding(
                finding_id="f1",
                rule_id="pdf.missing-alt-text",
                success_criterion="1.1.1",
                locator=_locator(),
            ),
        ),
        allowed_operations=(AllowedOperation(op="set_alt_text", format=DocumentFormat.PDF),),
        text_context="page 1 text",
    )
    parsed = json.loads(manifest.to_json())
    assert parsed["document_id"] == "doc-1"
    assert parsed["findings"][0]["finding_id"] == "f1"
    assert parsed["document_format"] == "pdf"


def test_parse_edit_response_happy_path():
    raw = {
        "contract_version": CONTRACT_VERSION,
        "request_id": "req-1",
        "source_sha256": "abc",
        "edits": [
            {
                "edit_id": "e1",
                "finding_ids": ["f1"],
                "locator": {
                    "format": "pdf",
                    "page_index": 0,
                    "part_name": None,
                    "element_ref": "structelem:1",
                    "fingerprint": "abc123",
                },
                "operation": "set_alt_text",
                "proposed_value": "A chart showing quarterly revenue.",
                "expected_original_value": None,
                "rationale": "figure lacked alt text",
            }
        ],
        "unresolved": [{"finding_id": "f2", "reason": "insufficient_evidence"}],
    }
    resp = parse_edit_response(raw)
    assert resp.request_id == "req-1"
    assert len(resp.edits) == 1
    assert resp.edits[0].operation == "set_alt_text"
    assert resp.unresolved[0].finding_id == "f2"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda raw: raw.pop("edits"),
        lambda raw: raw.__setitem__("contract_version", "document-wide-ai.v99"),
        lambda raw: raw.__setitem__("edits", "not-a-list"),
        lambda raw: raw["edits"].append({"edit_id": "e2"}),  # missing required fields
    ],
)
def test_parse_edit_response_rejects_malformed(mutate):
    raw = {
        "contract_version": CONTRACT_VERSION,
        "request_id": "req-1",
        "source_sha256": "abc",
        "edits": [],
        "unresolved": [],
    }
    mutate(raw)
    with pytest.raises(ContractError):
        parse_edit_response(raw)
