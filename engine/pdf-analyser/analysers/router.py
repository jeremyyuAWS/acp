"""Dispatches analysis jobs to the appropriate analyser based on file type."""

from __future__ import annotations

from pathlib import Path

from models.manifest import AnalysisJob, AnalyserResult, FileType
from exceptions import UnsupportedFileTypeError


async def run_analyser(file_path: Path, job: AnalysisJob) -> AnalyserResult:
    """
    Dispatch to the correct analyser based on job.file_type.
    Importing analysers here (not at module level) keeps startup fast and
    avoids loading Playwright until it's actually needed.
    """
    if job.file_type == FileType.HTML:
        from analysers.html_analyser import HtmlAnalyser
        return await HtmlAnalyser().analyse(file_path, job)

    if job.file_type == FileType.PDF:
        from analysers.pdf_analyser import PdfAnalyser
        return await PdfAnalyser().analyse(file_path, job)

    raise UnsupportedFileTypeError(str(job.file_type))
