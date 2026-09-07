"""Read-only remediation automation policy preview API."""
from fastapi import APIRouter
from pydantic import BaseModel, Field

from remediation_automation_policy import build_policy_preview

router = APIRouter()


class PolicyPreviewRequest(BaseModel):
    findings: list[dict]
    level: int | None = Field(default=None, ge=1, le=5)


@router.post("/remediation/automation-policy/preview")
def remediation_policy_preview(body: PolicyPreviewRequest):
    return build_policy_preview(body.findings, level=body.level)
