"""
RemediationEngine — 4-stage pipeline:
  1. Receive  — RemediationJob with IssueManifest + download URL
  2. Dispatch — each issue looked up in fixer_registry
  3. Apply    — fixer mutates a copy of the document
  4. Return   — RemediationResultPayload

HTML: loads document with BeautifulSoup, applies all HTML fixers, serialises back to bytes.
PDF:  opens document with pikepdf, applies all PDF fixers, saves to output path.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import tempfile
from pathlib import Path
from uuid import uuid4

import pikepdf
from bs4 import BeautifulSoup

from models.manifest import (
    A11yIssue,
    AppliedFixPayload,
    FileType,
    IssueCategory,
    RemediationResultPayload,
    RemediationType,
    SkippedFixPayload,
)
from remediation.base_fixer import FixBehavior, FixStatus
from remediation.fixer_registry import build_registry

logger = logging.getLogger(__name__)

_REMEDIATOR_VERSION = "1.0.0"


class RemediationEngine:
    def __init__(self, mcp_client=None) -> None:
        self._registry = build_registry(mcp_client)

    async def remediate(self, source_path: Path, job, behavior: FixBehavior | None = None) -> tuple[RemediationResultPayload, Path | None]:
        resolved_behavior = behavior or FixBehavior.default()
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._remediate_sync, source_path, job, resolved_behavior)

    def _remediate_sync(self, source_path: Path, job, behavior: FixBehavior) -> tuple[RemediationResultPayload, Path | None]:
        file_type: FileType = job.file_type
        manifest = job.manifest

        if manifest is None or not manifest.all_issues:
            logger.info("Remediation job %s: no issues to fix.", job.job_id)
            return RemediationResultPayload(
                job_id=job.job_id,
                file_id=job.file_id,
                remediator_version=_REMEDIATOR_VERSION,
            ), None

        if file_type == FileType.PDF:
            return self._remediate_pdf(source_path, job, manifest.all_issues, behavior)
        elif file_type == FileType.HTML:
            return self._remediate_html(source_path, job, manifest.all_issues, behavior)
        else:
            # No fixers for this type — skip everything
            skipped = [
                SkippedFixPayload(
                    issue_id=issue.issue_id,
                    category=issue.category,
                    reason=f"File type {file_type.name} is not supported by the Python remediator",
                )
                for issue in manifest.all_issues
            ]
            return RemediationResultPayload(
                job_id=job.job_id,
                file_id=job.file_id,
                skipped_count=len(skipped),
                skipped_fixes=skipped,
                remediator_version=_REMEDIATOR_VERSION,
            ), None

    # ── PDF ───────────────────────────────────────────────────────────────────

    def _remediate_pdf(self, source_path: Path, job, issues: list[A11yIssue], behavior: FixBehavior) -> tuple[RemediationResultPayload, Path | None]:
        tmp_dir = Path(tempfile.mkdtemp(prefix="digital-a11y-remediation-"))
        output_path = tmp_dir / f"{source_path.stem}_remediated{source_path.suffix}"
        shutil.copy2(source_path, output_path)

        applied: list[AppliedFixPayload] = []
        skipped: list[SkippedFixPayload] = []
        metadata = {
            "file_name": source_path.name,
            "language": "en",
            # source_path (not output_path) — pikepdf has output_path open for writing,
            # so pypdfium2 renders from the original copy to avoid file-lock conflicts
            "source_path": str(source_path),
        }

        try:
            with pikepdf.open(output_path, allow_overwriting_input=True) as pdf:
                for issue in _sort_by_severity(issues):
                    fixer = self._registry.get((issue.rule_id, FileType.PDF))
                    if fixer is None:
                        skipped.append(SkippedFixPayload(
                            issue_id=issue.issue_id,
                            category=issue.category,
                            reason="No automated fixer available for this rule",
                        ))
                        continue

                    result = fixer.apply(pdf, issue, metadata, behavior)

                    if result.status == FixStatus.FIXED:
                        applied.append(AppliedFixPayload(
                            issue_id=issue.issue_id,
                            category=issue.category,
                            remediation_type=issue.remediation_type,
                            description=result.description,
                        ))
                    else:
                        skipped.append(SkippedFixPayload(
                            issue_id=issue.issue_id,
                            category=issue.category,
                            reason=result.description,
                        ))

                pdf.save(output_path)
        except Exception as exc:
            logger.error("PDF remediation failed for job %s: %s", job.job_id, exc, exc_info=True)
            # Return what we have — no output file, original will be used
            return RemediationResultPayload(
                job_id=job.job_id,
                file_id=job.file_id,
                skipped_count=len(issues),
                skipped_fixes=[
                    SkippedFixPayload(
                        issue_id=i.issue_id,
                        category=i.category,
                        reason=f"Remediation failed: {exc}",
                    )
                    for i in issues
                ],
                remediator_version=_REMEDIATOR_VERSION,
            ), None

        applied_ids = {f.issue_id for f in applied}
        human_required = sum(
            1 for i in issues
            if i.issue_id not in applied_ids
            and i.remediation_type == RemediationType.HUMAN_REQUIRED
        )

        return RemediationResultPayload(
            job_id=job.job_id,
            file_id=job.file_id,
            auto_fixed_count=len(applied),
            human_required_count=human_required,
            skipped_count=len(skipped),
            applied_fixes=applied,
            skipped_fixes=skipped,
            remediator_version=_REMEDIATOR_VERSION,
        ), output_path

    # ── HTML ──────────────────────────────────────────────────────────────────

    def _remediate_html(self, source_path: Path, job, issues: list[A11yIssue], behavior: FixBehavior) -> tuple[RemediationResultPayload, Path | None]:
        tmp_dir = Path(tempfile.mkdtemp(prefix="digital-a11y-remediation-"))
        output_path = tmp_dir / f"{source_path.stem}_remediated{source_path.suffix}"

        content = source_path.read_bytes()
        soup = BeautifulSoup(content, "lxml")

        applied: list[AppliedFixPayload] = []
        skipped: list[SkippedFixPayload] = []
        metadata = {
            "file_name": source_path.name,
            "language": "en",
        }

        for issue in _sort_by_severity(issues):
            fixer = self._registry.get((issue.rule_id, FileType.HTML))
            if fixer is None:
                skipped.append(SkippedFixPayload(
                    issue_id=issue.issue_id,
                    category=issue.category,
                    reason="No automated fixer available for this rule",
                ))
                continue

            try:
                result = fixer.apply(soup, issue, metadata, behavior)
            except Exception as exc:
                skipped.append(SkippedFixPayload(
                    issue_id=issue.issue_id,
                    category=issue.category,
                    reason=f"Fixer error: {exc}",
                ))
                continue

            if result.status == FixStatus.FIXED:
                applied.append(AppliedFixPayload(
                    issue_id=issue.issue_id,
                    category=issue.category,
                    remediation_type=issue.remediation_type,
                    description=result.description,
                ))
            else:
                skipped.append(SkippedFixPayload(
                    issue_id=issue.issue_id,
                    category=issue.category,
                    reason=result.description,
                ))

        output_path.write_bytes(soup.encode("utf-8"))

        applied_ids = {f.issue_id for f in applied}
        human_required = sum(
            1 for i in issues
            if i.issue_id not in applied_ids
            and i.remediation_type == RemediationType.HUMAN_REQUIRED
        )

        return RemediationResultPayload(
            job_id=job.job_id,
            file_id=job.file_id,
            auto_fixed_count=len(applied),
            human_required_count=human_required,
            skipped_count=len(skipped),
            applied_fixes=applied,
            skipped_fixes=skipped,
            remediator_version=_REMEDIATOR_VERSION,
        ), output_path


def _sort_by_severity(issues: list[A11yIssue]) -> list[A11yIssue]:
    return sorted(issues, key=lambda i: i.severity.value)
