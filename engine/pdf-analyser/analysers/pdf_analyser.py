"""
PDF accessibility analyser.
Orchestrates all registered PDF rules using pikepdf + pdfplumber.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path

import pikepdf
import pdfplumber

from analysers.base import BaseAnalyser
from analysers.rules.pdf.bookmarks import BookmarksRule
from analysers.rules.pdf.display_title import DisplayTitleRule
from analysers.rules.pdf.document_language import DocumentLanguageRule
from analysers.rules.pdf.document_title import DocumentTitleRule
from analysers.rules.pdf.image_alt_text import ImageAltTextRule
from analysers.rules.pdf.reading_order import ReadingOrderRule
from analysers.rules.pdf.table_headers import TableHeadersRule
from analysers.rules.pdf.tagged_pdf import TaggedPdfRule
from models.manifest import AnalyserError, AnalyserResult, AnalysisJob

logger = logging.getLogger(__name__)

_RULES = [
    TaggedPdfRule(),
    DocumentTitleRule(),
    DisplayTitleRule(),
    DocumentLanguageRule(),
    ImageAltTextRule(),
    TableHeadersRule(),
    ReadingOrderRule(),
    BookmarksRule(),
]


class PdfAnalyser(BaseAnalyser):
    ANALYSER_NAME = "pdf-wcag-analyser"
    ANALYSER_VERSION = "1.0.0"

    async def analyse(self, file_path: Path, job: AnalysisJob) -> AnalyserResult:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._analyse_sync, file_path, job)

    def _analyse_sync(self, file_path: Path, job: AnalysisJob) -> AnalyserResult:
        started_at = datetime.now(timezone.utc)
        issues = []
        errors: list[AnalyserError] = []
        disabled = set(job.disabled_rule_ids)

        try:
            pdf = pikepdf.open(file_path)
            plumber_pdf = pdfplumber.open(file_path)
        except Exception as exc:
            logger.error("Failed to open PDF %s: %s", file_path, exc)
            return AnalyserResult(
                analyser_name=self.ANALYSER_NAME,
                analyser_version=self.ANALYSER_VERSION,
                started_at=started_at,
                completed_at=datetime.now(timezone.utc),
                succeeded=False,
                issues=[],
                errors=[AnalyserError(error_type=type(exc).__name__, message=str(exc))],
            )

        try:
            for rule in _RULES:
                if rule.rule_id in disabled:
                    logger.debug("Rule '%s' disabled — skipping.", rule.rule_id)
                    continue
                try:
                    rule_issues = rule.check(pdf, plumber_pdf)
                    issues.extend(rule_issues)
                    logger.debug("Rule '%s': %d issues.", rule.rule_id, len(rule_issues))
                except Exception as exc:
                    logger.warning("Rule '%s' error: %s", rule.rule_id, exc, exc_info=True)
                    errors.append(
                        AnalyserError(
                            rule_id=rule.rule_id,
                            error_type=type(exc).__name__,
                            message=str(exc),
                        )
                    )
        finally:
            try:
                pdf.close()
                plumber_pdf.close()
            except Exception:
                pass

        return AnalyserResult(
            analyser_name=self.ANALYSER_NAME,
            analyser_version=self.ANALYSER_VERSION,
            started_at=started_at,
            completed_at=datetime.now(timezone.utc),
            succeeded=True,
            issues=issues,
            errors=errors,
        )
