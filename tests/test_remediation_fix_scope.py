"""Automatic remediation runs only fixers justified by Assessment evidence."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

import handlers  # noqa: E402


def test_fix_scope_intersects_assessment_failures_with_frozen_scope(monkeypatch):
    monkeypatch.setattr(handlers, "_remediation_scope",
                        lambda _filename, _scan_id: lambda sc: sc != "2.4.2")

    allows = handlers._remediation_fix_scope(
        "report.pdf", "scan-1", ["1.4.3", "2.4.2"])

    assert allows("1.4.3") is True
    assert allows("2.4.2") is False       # failed, but excluded by frozen scan scope
    assert allows("1.1.1") is False       # in policy scope, but did not fail


def test_fix_scope_without_recorded_scan_scope_still_requires_a_failure(monkeypatch):
    monkeypatch.setattr(handlers, "_remediation_scope", lambda *_args: None)

    allows = handlers._remediation_fix_scope("report.docx", "scan-1", ["3.1.1"])

    assert allows("3.1.1") is True
    assert allows("1.4.3") is False


def test_fix_scope_fails_closed_when_failure_evidence_is_unavailable(monkeypatch):
    monkeypatch.setattr(handlers, "_remediation_scope", lambda *_args: None)

    allows = handlers._remediation_fix_scope("report.pdf", "scan-1", None)

    assert allows("1.4.3") is False

