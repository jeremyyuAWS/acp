"""A deterministic, offline stand-in for a provider call. No network. Tests configure
canned responses per request_id (or a default-response function) and assert on
`call_count` to prove one request per accepted package (PRD acceptance criterion 3).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from experiments.document_wide_ai.contracts.v1 import (
    CONTRACT_VERSION,
    EditResponseEnvelope,
    ProposedEdit,
    UnresolvedEntry,
    parse_edit_response,
)
from experiments.document_wide_ai.request.builder import GenerationRequest


def raw_envelope(
    *,
    source_sha256: str,
    request_id: str = "mock-request-1",
    edits: list[dict[str, Any]] | None = None,
    unresolved: list[dict[str, str]] | None = None,
    contract_version: str = CONTRACT_VERSION,
) -> dict[str, Any]:
    """Build a raw (dict) response envelope shaped exactly as a real provider response
    would be JSON-decoded, for feeding into `parse_edit_response` or a MockProvider.
    """
    return {
        "contract_version": contract_version,
        "request_id": request_id,
        "source_sha256": source_sha256,
        "edits": edits or [],
        "unresolved": unresolved or [],
    }


def edit_dict(
    *,
    edit_id: str,
    finding_ids: list[str],
    locator_format: str,
    element_ref: str,
    fingerprint: str,
    operation: str,
    proposed_value: Any,
    page_index: int | None = None,
    part_name: str | None = None,
    expected_original_value: Any = None,
    rationale: str = "",
) -> dict[str, Any]:
    return {
        "edit_id": edit_id,
        "finding_ids": finding_ids,
        "locator": {
            "format": locator_format,
            "page_index": page_index,
            "part_name": part_name,
            "element_ref": element_ref,
            "fingerprint": fingerprint,
        },
        "operation": operation,
        "proposed_value": proposed_value,
        "expected_original_value": expected_original_value,
        "rationale": rationale,
    }


@dataclass
class MockProvider:
    """`responses` maps request_id -> raw envelope dict. `default_response_fn`, when set,
    is called with the GenerationRequest for any request_id not in `responses`.
    """

    responses: dict[str, dict[str, Any]] = field(default_factory=dict)
    default_response_fn: Callable[[GenerationRequest], dict[str, Any]] | None = None
    call_log: list[GenerationRequest] = field(default_factory=list, init=False)

    def generate(self, request: GenerationRequest) -> EditResponseEnvelope:
        self.call_log.append(request)
        if request.request_id in self.responses:
            raw = self.responses[request.request_id]
        elif self.default_response_fn is not None:
            raw = self.default_response_fn(request)
        else:
            raise LookupError(f"MockProvider: no response configured for request_id={request.request_id!r}")
        return parse_edit_response(raw)

    @property
    def call_count(self) -> int:
        return len(self.call_log)
