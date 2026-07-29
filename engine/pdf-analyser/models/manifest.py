"""
Pydantic v2 models that mirror the C# contracts in DigitalA11y.Core.

Serialisation notes:
- ASP.NET Core server uses JsonStringEnumConverter: camelCase property names, string enum values (e.g. "PDF").
- We use alias_generator=to_camel so model_dump(by_alias=True) produces camelCase keys.
- Enums are IntEnum so they serialise as integers matching C# defaults.
- Use model_dump(by_alias=True, mode="json") when posting to the server.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from enum import IntEnum
from typing import Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


# ── Alias helper ──────────────────────────────────────────────────────────────

def _to_camel(s: str) -> str:
    """Convert snake_case to camelCase."""
    parts = s.split("_")
    return parts[0] + "".join(p.capitalize() for p in parts[1:])


_CAMEL_CONFIG = ConfigDict(
    populate_by_name=True,
    alias_generator=_to_camel,
)


# ── Enums (IntEnum = serialises as integer, matching C# default) ──────────────
# The server uses JsonStringEnumConverter so it may send string names (e.g. "PDF")
# instead of integers. _missing_ lets IntEnum accept string names transparently.

class _StrNameIntEnum(IntEnum):
    @classmethod
    def _missing_(cls, value: object):
        if isinstance(value, str):
            try:
                return cls[value.upper()]
            except KeyError:
                return None
        return None


class FileType(_StrNameIntEnum):
    UNKNOWN = 0
    PDF = 1
    DOCX = 2
    PPTX = 3
    HTML = 4
    XLSX = 5


class IssueSeverity(_StrNameIntEnum):
    CRITICAL = 0
    SERIOUS = 1
    MODERATE = 2
    MINOR = 3


class IssueCategory(_StrNameIntEnum):
    ALT_TEXT = 0
    COLOUR_CONTRAST = 1
    DOCUMENT_TITLE = 2
    LANGUAGE = 3
    HEADING_STRUCTURE = 4
    READING_ORDER = 5
    LINKS = 6
    TABLES = 7
    LISTS = 8
    FORMS = 9
    IMAGES_OF_TEXT = 10
    FLASHING_CONTENT = 11
    AUDIO_VIDEO = 12
    KEYBOARD_NAVIGATION = 13
    FOCUS_VISIBLE = 14
    ERROR_IDENTIFICATION = 15
    PARSING = 16
    NAME_ROLE_VALUE = 17


class WcagCriterion(_StrNameIntEnum):
    SC_1_1_1 = 0
    SC_1_3_1 = 1
    SC_1_3_2 = 2
    SC_1_4_1 = 3
    SC_1_4_3 = 4
    SC_1_4_4 = 5
    SC_1_4_5 = 6
    SC_2_1_1 = 7
    SC_2_4_2 = 8
    SC_2_4_4 = 9
    SC_2_4_6 = 10
    SC_3_1_1 = 11
    SC_4_1_1 = 12
    SC_4_1_2 = 13
    SC_4_1_3 = 14


class RemediationType(_StrNameIntEnum):
    AUTO_FIX = 0
    AUTO_PLACEHOLDER = 1
    HUMAN_REQUIRED = 2
    ACCEPTED_RISK = 3


# ── Manifest sub-models ───────────────────────────────────────────────────────

class IssueLocation(BaseModel):
    model_config = _CAMEL_CONFIG

    page_number: Optional[int] = None
    slide_number: Optional[int] = None
    element_index: Optional[int] = None
    x_path: Optional[str] = None
    description: Optional[str] = None


class IssueEvidence(BaseModel):
    model_config = _CAMEL_CONFIG

    snippet: Optional[str] = None
    computed_value: Optional[str] = None
    expected_value: Optional[str] = None
    additional_context: Optional[dict[str, str]] = None


class A11yIssue(BaseModel):
    model_config = _CAMEL_CONFIG

    issue_id: UUID = Field(default_factory=uuid4)
    rule_id: str
    title: str
    description: str
    severity: IssueSeverity
    category: IssueCategory
    wcag_criterion: WcagCriterion
    location: IssueLocation = Field(default_factory=IssueLocation)
    evidence: IssueEvidence = Field(default_factory=IssueEvidence)
    remediation_type: RemediationType
    remediation_guidance: Optional[str] = None


class AnalyserError(BaseModel):
    model_config = _CAMEL_CONFIG

    rule_id: Optional[str] = None
    error_type: str = ""
    message: str = ""


class AnalyserResult(BaseModel):
    model_config = _CAMEL_CONFIG

    analyser_name: str
    analyser_version: str
    started_at: datetime
    completed_at: datetime
    succeeded: bool
    issues: list[A11yIssue] = Field(default_factory=list)
    errors: list[AnalyserError] = Field(default_factory=list)


class FileMetadata(BaseModel):
    model_config = _CAMEL_CONFIG

    file_id: UUID
    file_name: str
    file_path: str
    file_type: FileType
    file_size_bytes: int
    mime_type: Optional[str] = None
    sha256_hash: Optional[str] = None
    last_modified: datetime


class IssueManifest(BaseModel):
    model_config = _CAMEL_CONFIG

    manifest_id: UUID = Field(default_factory=uuid4)
    job_id: UUID
    batch_run_id: UUID
    file: FileMetadata
    analyser_results: list[AnalyserResult] = Field(default_factory=list)
    all_issues: list[A11yIssue] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    schema_version: str = "1.0"


# ── Job models ────────────────────────────────────────────────────────────────

class AnalysisJob(BaseModel):
    model_config = _CAMEL_CONFIG

    job_id: UUID
    batch_run_id: UUID
    file_id: UUID
    file_path: str
    file_type: FileType
    queue: str
    enqueued_at: datetime
    department_id: UUID
    disabled_rule_ids: list[str] = Field(default_factory=list)


# ── API request/response models ───────────────────────────────────────────────

class NextJobResponse(BaseModel):
    model_config = _CAMEL_CONFIG

    has_job: bool
    job: Optional[AnalysisJob] = None
    tenant_slug: Optional[str] = None


class ClaimJobRequest(BaseModel):
    model_config = _CAMEL_CONFIG

    worker_id: str
    queue: str
    supported_file_types: list[FileType]


class ClaimJobResponse(BaseModel):
    model_config = _CAMEL_CONFIG

    claimed: bool
    job: Optional[AnalysisJob] = None
    claim_token: Optional[str] = None
    reason: Optional[str] = None


class SubmitResultRequest(BaseModel):
    model_config = _CAMEL_CONFIG

    job_id: UUID
    claim_token: str
    manifest: IssueManifest


class FailJobRequest(BaseModel):
    model_config = _CAMEL_CONFIG

    job_id: UUID
    claim_token: str
    error_code: str
    error_message: str
    stack_trace: Optional[str] = None
    is_retryable: bool = True


class ProgressUpdateRequest(BaseModel):
    model_config = _CAMEL_CONFIG

    job_id: UUID
    claim_token: str
    items_processed: int
    total_items: Optional[int] = None
    status_message: Optional[str] = None


# ── Remediation models ────────────────────────────────────────────────────────

class RemediationJob(BaseModel):
    model_config = _CAMEL_CONFIG

    job_id: UUID
    batch_run_id: UUID
    file_id: UUID
    file_path: str
    file_type: FileType
    queue: str
    enqueued_at: datetime
    department_id: UUID
    manifest: Optional[IssueManifest] = None
    disabled_rule_ids: list[str] = Field(default_factory=list)


class NextRemediationJobResponse(BaseModel):
    model_config = _CAMEL_CONFIG

    job_id: UUID
    batch_run_id: UUID
    file_id: UUID
    analysis_job_id: UUID
    file_identifier: str
    file_type: FileType
    queue: str
    created_at: datetime
    manifest: Optional[IssueManifest] = None
    tenant_slug: Optional[str] = None


class ClaimRemediationJobResponse(BaseModel):
    model_config = _CAMEL_CONFIG

    claimed: bool
    job: Optional[RemediationJob] = None
    claim_token: Optional[str] = None
    reason: Optional[str] = None
    allow_llm: bool = True
    allow_placeholders: bool = True


class AppliedFixPayload(BaseModel):
    model_config = _CAMEL_CONFIG

    issue_id: UUID
    category: IssueCategory
    remediation_type: RemediationType
    description: str


class SkippedFixPayload(BaseModel):
    model_config = _CAMEL_CONFIG

    issue_id: UUID
    category: IssueCategory
    reason: str


class LlmUsageEntry(BaseModel):
    model_config = _CAMEL_CONFIG

    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    provider: str = "Unknown"
    model: str = ""
    job_type: str = "Remediation"
    issue_id: UUID | None = None
    department_id: UUID | None = None


class RemediationResultPayload(BaseModel):
    model_config = _CAMEL_CONFIG

    job_id: UUID
    file_id: UUID
    auto_fixed_count: int = 0
    human_required_count: int = 0
    skipped_count: int = 0
    applied_fixes: list[AppliedFixPayload] = Field(default_factory=list)
    skipped_fixes: list[SkippedFixPayload] = Field(default_factory=list)
    remediator_version: str = "1.0.0"
    llm_usage: list[LlmUsageEntry] = Field(default_factory=list)
