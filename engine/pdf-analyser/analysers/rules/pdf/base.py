"""Base protocol for PDF accessibility rules."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import pikepdf
import pdfplumber

from models.manifest import A11yIssue


@runtime_checkable
class IPdfRule(Protocol):
    rule_id: str

    def check(self, pdf: pikepdf.Pdf, plumber_pdf: pdfplumber.PDF) -> list[A11yIssue]:
        ...
