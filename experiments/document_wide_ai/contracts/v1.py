"""Versioned document-context / edit-response contract (v1) for the document-wide AI
fixes prototype. See ../README.md for scope and ADR 0056 for how this relates to (and is
deliberately isolated from) the shipped provider waterfall.

Everything here is a plain, JSON-serializable dataclass. No network, DB, or filesystem
access happens in this module.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

CONTRACT_VERSION = "document-wide-ai.v1"


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class DocumentFormat(str, Enum):
    PDF = "pdf"
    DOCX = "docx"


class EvidenceKind(str, Enum):
    TEXT = "text"
    IMAGE = "image"


@dataclass(frozen=True)
class Locator:
    """A stable reference into a document's structure.

    PDF: page identity plus, when available, the structure-tree element or object
    reference the finding is anchored to (e.g. a /Figure struct element, a catalog key).
    DOCX: package part name plus an element reference (an XPath-like path within that
    part). Page numbers alone are never a valid DOCX locator — pagination is not stable
    across renderers.
    """

    format: DocumentFormat
    page_index: int | None  # 0-based; PDF only. None for DOCX or page-independent PDF targets.
    part_name: str | None  # DOCX package part, e.g. "word/document.xml". None for PDF.
    element_ref: str  # PDF: struct-element id or object ref, e.g. "structelem:12" or "catalog:/Lang".
    # DOCX: element path, e.g. "word/document.xml::/w:document/w:body/w:p[4]/w:drawing".
    fingerprint: str  # short hash of the current value at this locator, for precondition checks.

    def key(self) -> tuple:
        return (self.format.value, self.page_index, self.part_name, self.element_ref)


@dataclass(frozen=True)
class Evidence:
    kind: EvidenceKind
    source_locator: Locator
    reason: str  # why this evidence was included (which finding needed it)
    text: str | None = None
    image_ref: str | None = None  # opaque id into the package's image table; never raw bytes here.


@dataclass(frozen=True)
class Finding:
    finding_id: str
    rule_id: str
    success_criterion: str  # e.g. "1.1.1"
    locator: Locator
    evidence_text: str = ""


@dataclass(frozen=True)
class AllowedOperation:
    op: str  # e.g. "set_alt_text", "set_document_language", "set_document_title"
    format: DocumentFormat
    value_constraints: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExtractionIssue:
    """A recorded failure or gap in context extraction. Never silently dropped."""

    kind: str  # e.g. "extraction_failed", "missing_visual_evidence"
    detail: str
    related_finding_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class DocumentContextManifest:
    """The frozen input to one generation request. Binds document identity, the exact
    findings in scope, and the operations the model is allowed to propose.
    """

    contract_version: str
    extractor_version: str
    adapter_version: str
    document_id: str
    document_format: DocumentFormat
    source_sha256: str
    assessment_revision: str
    selected_criteria: tuple[str, ...]
    findings: tuple[Finding, ...]
    allowed_operations: tuple[AllowedOperation, ...]
    text_context: str  # extracted text/structure package, stable-prefix ordered
    evidence: tuple[Evidence, ...] = ()
    extraction_issues: tuple[ExtractionIssue, ...] = ()

    def finding_ids(self) -> frozenset[str]:
        return frozenset(f.finding_id for f in self.findings)

    def to_json(self) -> str:
        return json.dumps(_to_jsonable(self), sort_keys=True)


@dataclass(frozen=True)
class ProposedEdit:
    edit_id: str
    finding_ids: tuple[str, ...]
    locator: Locator
    operation: str
    proposed_value: Any
    expected_original_value: Any
    rationale: str = ""


@dataclass(frozen=True)
class UnresolvedEntry:
    finding_id: str
    reason: str  # e.g. "no_safe_operation", "insufficient_evidence", "requires_review"


@dataclass(frozen=True)
class EditResponseEnvelope:
    contract_version: str
    request_id: str
    source_sha256: str
    edits: tuple[ProposedEdit, ...]
    unresolved: tuple[UnresolvedEntry, ...]

    def to_json(self) -> str:
        return json.dumps(_to_jsonable(self), sort_keys=True)


def _to_jsonable(obj: Any) -> Any:
    if hasattr(obj, "__dataclass_fields__"):
        return {k: _to_jsonable(v) for k, v in asdict(obj).items()}
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, (list, tuple)):
        return [_to_jsonable(v) for v in obj]
    if isinstance(obj, dict):
        return {k: _to_jsonable(v) for k, v in obj.items()}
    return obj


class ContractError(ValueError):
    """Raised for malformed/truncated envelopes or manifests that fail structural checks."""


def parse_edit_response(raw: dict[str, Any]) -> EditResponseEnvelope:
    """Parse and structurally validate a raw (e.g. JSON-decoded) response envelope.

    Raises ContractError for anything malformed or truncated. Does NOT validate edits
    against a manifest — see validation/validator.py for that.
    """
    required_top = ("contract_version", "request_id", "source_sha256", "edits", "unresolved")
    missing = [k for k in required_top if k not in raw]
    if missing:
        raise ContractError(f"missing top-level fields: {missing}")
    if raw["contract_version"] != CONTRACT_VERSION:
        raise ContractError(f"unsupported contract_version: {raw['contract_version']!r}")
    if not isinstance(raw["edits"], list) or not isinstance(raw["unresolved"], list):
        raise ContractError("edits/unresolved must be lists")

    edits = []
    for i, e in enumerate(raw["edits"]):
        try:
            locator = Locator(
                format=DocumentFormat(e["locator"]["format"]),
                page_index=e["locator"].get("page_index"),
                part_name=e["locator"].get("part_name"),
                element_ref=e["locator"]["element_ref"],
                fingerprint=e["locator"]["fingerprint"],
            )
            edits.append(
                ProposedEdit(
                    edit_id=e["edit_id"],
                    finding_ids=tuple(e["finding_ids"]),
                    locator=locator,
                    operation=e["operation"],
                    proposed_value=e["proposed_value"],
                    expected_original_value=e.get("expected_original_value"),
                    rationale=e.get("rationale", ""),
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ContractError(f"malformed edit at index {i}: {exc}") from exc

    unresolved = []
    for i, u in enumerate(raw["unresolved"]):
        try:
            unresolved.append(UnresolvedEntry(finding_id=u["finding_id"], reason=u["reason"]))
        except (KeyError, TypeError) as exc:
            raise ContractError(f"malformed unresolved entry at index {i}: {exc}") from exc

    return EditResponseEnvelope(
        contract_version=raw["contract_version"],
        request_id=raw["request_id"],
        source_sha256=raw["source_sha256"],
        edits=tuple(edits),
        unresolved=tuple(unresolved),
    )
