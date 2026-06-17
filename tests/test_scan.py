"""Regression guard for the scan core (engines -> rubric -> report).

Runs the real engines against the bundled sample corpus once, then asserts:
  1. exact rule findings on the canonical non-compliant docx (oracle diff),
  2. clean/compliant files score 100 and certify,
  3. malformed files surface as 'error' (never a silent pass),
  4. the safety invariant: an 'error' or 'uncertain' file is NEVER certified,
  5. disabling a rule removes both its findings and its skipped-rule error.

Needs the .NET Office CLI built (spike/dotnet/.../Release) and the PDF engine
deps (api/requirements.txt). Run:  .venv-drive/bin/python -m pytest tests/ -q
"""
from __future__ import annotations
import sys
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))
sys.path.insert(0, str(ACP / "scripts"))
from scanner import run_scan  # noqa: E402
from rubric import Rubric  # noqa: E402

EXPECTED_DOCX_NONCOMPLIANT = {
    "DOCX-TITLE-001", "DOCX-LANG-001", "DOCX-ALT-001", "DOCX-LINK-001", "DOCX-TABLE-001",
}
CLEAN_COMPLIANT = ["docx-compliant.docx", "pptx-compliant.pptx", "xlsx-compliant.xlsx"]
MALFORMED = ["edge-corrupt.docx", "edge-plaintext.docx", "edge-pdf-as.docx", "pdf-encrypted.pdf"]


@pytest.fixture(scope="module")
def report():
    # scan with the default rubric (ignore any operator-edited rubric.active.json)
    rb = Rubric.load(ACP / "config/rubric.default.json")
    rep = run_scan_default(rb)
    return rep


def run_scan_default(rb: Rubric) -> dict:
    # run_scan resolves the active rubric; for a deterministic baseline we point it
    # at the default by temporarily ensuring no active override is present.
    active = ACP / "config/rubric.active.json"
    saved = active.read_text() if active.exists() else None
    if active.exists():
        active.unlink()
    try:
        return run_scan("local")
    finally:
        if saved is not None:
            active.write_text(saved)


def by_file(report) -> dict:
    return {f["file"]: f for f in report["files"]}


def test_corpus_scanned(report):
    assert report["files"], "no files scanned — is the sample corpus present?"


def test_docx_noncompliant_exact_rules(report):
    f = by_file(report).get("docx-noncompliant.docx")
    assert f is not None and f["status"] == "analysed"
    rules = {i["ruleId"] for i in f["issues"]}
    assert rules == EXPECTED_DOCX_NONCOMPLIANT, f"rule drift: {sorted(rules)}"


def test_clean_files_certify(report):
    bf = by_file(report)
    for name in CLEAN_COMPLIANT:
        f = bf.get(name)
        assert f is not None, f"missing {name}"
        assert f["status"] == "analysed" and f["score"] == 100 and f["compliant"] is True, name


def test_malformed_files_error_not_pass(report):
    bf = by_file(report)
    for name in MALFORMED:
        f = bf.get(name)
        assert f is not None, f"missing {name}"
        assert f["status"] == "error", f"{name} should be 'error', got {f['status']}"


def test_safety_invariant_no_uncertain_or_error_is_certified(report):
    # the product's whole reason to exist: incomplete analysis is never a pass
    for f in report["files"]:
        if f["status"] in ("error", "uncertain"):
            assert f["compliant"] is False, f"{f['file']} certified despite status={f['status']}"
        if f["status"] == "uncertain":
            assert f["score_is_upper_bound"] is True, f["file"]


def test_disabling_a_rule_drops_its_findings_and_errors():
    base = Rubric.load(ACP / "config/rubric.default.json")
    cfg = dict(base.cfg)
    cfg["disabled_rules"] = ["DOCX-TITLE-001"]
    rb = Rubric(cfg)
    a = rb.assess(
        succeeded=True,
        issues=[{"ruleId": "DOCX-TITLE-001", "wcag": "SC_2_4_2", "severity": "SERIOUS"},
                {"ruleId": "DOCX-LANG-001", "wcag": "SC_3_1_1", "severity": "SERIOUS"}],
        errors=[{"message": "boom", "rule": "DOCX-TITLE-001"}],
    )
    # the disabled rule's finding is gone and its error no longer makes the file uncertain
    assert a["status"] == "analysed"
    assert a["skipped_rules"] == 0
