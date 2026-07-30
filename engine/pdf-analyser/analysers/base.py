"""Abstract base class for all analysers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from models.manifest import AnalysisJob, AnalyserResult


class BaseAnalyser(ABC):
    ANALYSER_NAME: str = ""
    ANALYSER_VERSION: str = "1.0.0"

    @abstractmethod
    async def analyse(self, file_path: Path, job: AnalysisJob) -> AnalyserResult:
        """Analyse *file_path* and return an AnalyserResult."""
