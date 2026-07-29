"""Abstract base class for all fixers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum

from models.manifest import A11yIssue


class FixStatus(Enum):
    FIXED = "fixed"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass
class FixBehavior:
    allow_llm: bool = True
    allow_placeholders: bool = True

    @classmethod
    def default(cls) -> "FixBehavior":
        return cls(allow_llm=True, allow_placeholders=True)


@dataclass
class FixerResult:
    status: FixStatus
    description: str
    issue_id: object = None  # UUID


class BaseFixer(ABC):
    """
    Base class for all fixers.
    apply() receives the document object (type depends on fixer family),
    the issue to fix, extra metadata, and fix behavior flags.
    Returns a FixerResult describing what happened.
    """

    @abstractmethod
    def apply(self, document: object, issue: A11yIssue, metadata: dict, behavior: FixBehavior = None) -> FixerResult:
        ...
