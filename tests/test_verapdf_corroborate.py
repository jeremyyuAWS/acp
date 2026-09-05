"""veraPDF REST corroboration engine — RECORDED and LIVE path tests.

RECORDED tests run always: they exercise parse_fixture() against pre-captured JSON
in tests/fixtures/verapdf_rest_*.json.  No Docker, no binary, no network.

LIVE tests run only when ACP_VERAPDF_REST is set to a reachable host (e.g. a test
container).  In CI they skip with a reason.

All three SC-corroboration signals are verified against the untagged fixture:
  1.3.1 Info and Relationships  (tagging, MarkInfo)
  2.4.2 Page Titled             (DisplayDocTitle)
  3.1.1 Language of Page        (natural language)
"""
from __future__ import annotations

import io
import json
import os
import sys
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))
import verapdf_corroborate as vc  # noqa: E402

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


# ── helpers ───────────────────────────────────────────────────────────────────────────────────────

def _load(name: str) -> dict:
    return json.loads((_FIXTURES / name).read_text())


# ══ 1. parse_fixture — RECORDED path ════════════════════════════════════════════════════════════

class TestParseFixtureUntagged:
    """pre-captured response for an untagged PDF — all three SCs should be corroborated."""

    def setup_method(self):
        self.result = vc.parse_fixture(_load("verapdf_rest_untagged.json"))

    def test_not_compliant(self):
        assert self.result.compliant is False

    def test_failed_checks_nonzero(self):
        assert self.result.failed_checks > 0

    def test_passed_checks_nonzero(self):
        assert self.result.passed_checks > 0

    def test_corroborates_1_3_1_tagging(self):
        assert "1.3.1 Info and Relationships" in self.result.corroborates

    def test_corroborates_2_4_2_page_titled(self):
        assert "2.4.2 Page Titled" in self.result.corroborates

    def test_corroborates_3_1_1_language(self):
        assert "3.1.1 Language of Page" in self.result.corroborates

    def test_failed_count_for_1_3_1_is_positive(self):
        count = self.result.corroborated_scs.get("1.3.1 Info and Relationships", 0)
        assert count > 0

    def test_failed_count_for_3_1_1_is_positive(self):
        count = self.result.corroborated_scs.get("3.1.1 Language of Page", 0)
        assert count > 0

    def test_xmp_metadata_clause_not_in_corroborated_scs(self):
        # 7.1-8 (XMP metadata) has no WCAG SC and must not appear as a corroboration signal
        for sc_label in self.result.corroborated_scs:
            assert "XMP" not in sc_label
            assert "metadata" not in sc_label.lower()

    def test_xmp_metadata_clause_in_extra(self):
        assert "7.1-8" in self.result.extra_clause_keys

    def test_no_unknown_sc_labels(self):
        known_scs = {"1.3.1 Info and Relationships", "2.4.2 Page Titled", "3.1.1 Language of Page"}
        for sc in self.result.corroborated_scs:
            assert sc in known_scs, f"unexpected SC label: {sc!r}"


class TestParseFixtureCompliant:
    """pre-captured response for a compliant PDF — no corroboration signals."""

    def setup_method(self):
        self.result = vc.parse_fixture(_load("verapdf_rest_compliant.json"))

    def test_is_compliant(self):
        assert self.result.compliant is True

    def test_no_corroborated_scs(self):
        assert self.result.corroborated_scs == {}

    def test_no_extra_clauses(self):
        assert self.result.extra_clause_keys == []

    def test_failed_checks_zero(self):
        assert self.result.failed_checks == 0

    def test_passed_checks_nonzero(self):
        assert self.result.passed_checks > 0


# ══ 2. parse_fixture — edge cases ═══════════════════════════════════════════════════════════════

def test_empty_jobs_returns_compliant_empty():
    data = {"report": {"jobs": []}}
    r = vc.parse_fixture(data)
    assert r.compliant is True
    assert r.corroborated_scs == {}


def test_rule_with_passed_status_ignored():
    data = {
        "report": {
            "jobs": [
                {
                    "validationResult": {
                        "compliant": True,
                        "details": {"passedChecks": 10, "failedChecks": 0},
                        "ruleSummaries": [
                            {"clause": "7.1", "testNumber": "3", "status": "PASSED", "failedChecks": 0}
                        ],
                    }
                }
            ]
        }
    }
    r = vc.parse_fixture(data)
    assert r.corroborated_scs == {}


def test_unknown_clause_goes_to_extra():
    data = {
        "report": {
            "jobs": [
                {
                    "validationResult": {
                        "compliant": False,
                        "details": {"passedChecks": 5, "failedChecks": 1},
                        "ruleSummaries": [
                            {"clause": "9.99", "testNumber": "42", "status": "FAILED", "failedChecks": 1}
                        ],
                    }
                }
            ]
        }
    }
    r = vc.parse_fixture(data)
    assert "9.99-42" in r.extra_clause_keys
    assert r.corroborated_scs == {}


def test_multiple_rules_for_same_sc_sum_counts():
    data = {
        "report": {
            "jobs": [
                {
                    "validationResult": {
                        "compliant": False,
                        "details": {"passedChecks": 5, "failedChecks": 3},
                        "ruleSummaries": [
                            {"clause": "6.2", "testNumber": "1", "status": "FAILED", "failedChecks": 1},
                            {"clause": "7.1", "testNumber": "3", "status": "FAILED", "failedChecks": 53},
                        ],
                    }
                }
            ]
        }
    }
    r = vc.parse_fixture(data)
    assert r.corroborated_scs.get("1.3.1 Info and Relationships") == 54


def test_missing_ruleSummaries_key():
    data = {
        "report": {
            "jobs": [
                {
                    "validationResult": {
                        "compliant": False,
                        "details": {"passedChecks": 5, "failedChecks": 2},
                    }
                }
            ]
        }
    }
    r = vc.parse_fixture(data)
    assert r.corroborated_scs == {}
    assert r.compliant is False


# ══ 3. SC_MAP completeness ════════════════════════════════════════════════════════════════════════

def test_sc_map_contains_1_3_1_for_markinfo():
    assert vc._SC_MAP.get("6.2-1") == "1.3.1 Info and Relationships"


def test_sc_map_contains_1_3_1_for_orphan_content():
    assert vc._SC_MAP.get("7.1-3") == "1.3.1 Info and Relationships"


def test_sc_map_contains_2_4_2_for_display_doc_title():
    assert vc._SC_MAP.get("7.1-11") == "2.4.2 Page Titled"


def test_sc_map_contains_3_1_1_for_language():
    sc = vc._SC_MAP.get("7.2-2") or vc._SC_MAP.get("7.2-1")
    assert sc == "3.1.1 Language of Page"


def test_xmp_metadata_clause_not_in_sc_map():
    # XMP metadata has no WCAG SC — must never be a corroboration signal
    assert "7.1-8" not in vc._SC_MAP


# ══ 4. LIVE path — corroborate_pdf ════════════════════════════════════════════════════════════════

def test_corroborate_pdf_returns_none_when_env_not_set(monkeypatch):
    monkeypatch.delenv("ACP_VERAPDF_REST", raising=False)
    result = vc.corroborate_pdf(b"%PDF-1.4 minimal")
    assert result is None


def test_corroborate_pdf_returns_none_on_connection_error(monkeypatch):
    monkeypatch.setenv("ACP_VERAPDF_REST", "http://localhost:18080")
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("connection refused")):
        result = vc.corroborate_pdf(b"%PDF-1.4 minimal")
    assert result is None


def test_corroborate_pdf_returns_none_on_json_error(monkeypatch):
    monkeypatch.setenv("ACP_VERAPDF_REST", "http://localhost:18080")
    mock_resp = MagicMock()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_resp.read.return_value = b"not-json"
    with patch("urllib.request.urlopen", return_value=mock_resp):
        result = vc.corroborate_pdf(b"%PDF-1.4")
    assert result is None


def test_corroborate_pdf_returns_result_on_success(monkeypatch):
    monkeypatch.setenv("ACP_VERAPDF_REST", "http://localhost:18080")
    fixture_bytes = (_FIXTURES / "verapdf_rest_untagged.json").read_bytes()
    mock_resp = MagicMock()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_resp.read.return_value = fixture_bytes
    with patch("urllib.request.urlopen", return_value=mock_resp):
        result = vc.corroborate_pdf(b"%PDF-1.4")
    assert result is not None
    assert result.compliant is False
    assert "1.3.1 Info and Relationships" in result.corroborates


def test_corroborate_pdf_posts_multipart_to_correct_url(monkeypatch):
    monkeypatch.setenv("ACP_VERAPDF_REST", "http://myhost:8080")
    fixture_bytes = (_FIXTURES / "verapdf_rest_compliant.json").read_bytes()
    captured: list = []
    mock_resp = MagicMock()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_resp.read.return_value = fixture_bytes

    def fake_urlopen(req, timeout=None):
        captured.append(req)
        return mock_resp

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        vc.corroborate_pdf(b"%PDF-1.4")

    assert len(captured) == 1
    req = captured[0]
    assert req.full_url == "http://myhost:8080/api/validate/ua1?format=json"
    assert req.method == "POST"
    assert "multipart/form-data" in req.get_header("Content-type")


def test_corroborate_pdf_returns_none_on_http_error(monkeypatch):
    monkeypatch.setenv("ACP_VERAPDF_REST", "http://localhost:18080")
    with patch("urllib.request.urlopen",
               side_effect=urllib.error.HTTPError(None, 500, "Internal Server Error", {}, None)):
        result = vc.corroborate_pdf(b"%PDF-1.4")
    assert result is None


# ══ 5. annotate_issues ════════════════════════════════════════════════════════════════════════════

def _make_issues():
    return [
        {"ruleId": "pdf.tagged", "wcag": "1.3.1 Info and Relationships", "severity": "CRITICAL"},
        {"ruleId": "pdf.display-doc-title", "wcag": "2.4.2 Page Titled", "severity": "MODERATE"},
        {"ruleId": "pdf.document-language", "wcag": "3.1.1 Language of Page", "severity": "SERIOUS"},
        {"ruleId": "pdf.some-other-rule", "wcag": "1.1.1 Non-text Content", "severity": "SERIOUS"},
    ]


def test_annotate_issues_adds_corroboration_to_matching_rules():
    result = vc.parse_fixture(_load("verapdf_rest_untagged.json"))
    issues = _make_issues()
    vc.annotate_issues(issues, result)
    tagged_issue = next(i for i in issues if i["ruleId"] == "pdf.tagged")
    assert "corroboration" in tagged_issue
    assert tagged_issue["corroboration"]["engine"] == "veraPDF/ua1"


def test_annotate_issues_non_corroborated_rule_unchanged():
    result = vc.parse_fixture(_load("verapdf_rest_untagged.json"))
    issues = _make_issues()
    vc.annotate_issues(issues, result)
    other = next(i for i in issues if i["ruleId"] == "pdf.some-other-rule")
    assert "corroboration" not in other


def test_annotate_issues_with_none_result_is_noop():
    issues = _make_issues()
    original = [dict(i) for i in issues]
    vc.annotate_issues(issues, None)
    assert issues == original


def test_annotate_issues_with_compliant_result_no_annotation():
    result = vc.parse_fixture(_load("verapdf_rest_compliant.json"))
    issues = _make_issues()
    vc.annotate_issues(issues, result)
    for issue in issues:
        assert "corroboration" not in issue


def test_annotate_issues_failed_checks_count_in_corroboration():
    result = vc.parse_fixture(_load("verapdf_rest_untagged.json"))
    issues = [{"ruleId": "pdf.document-language", "wcag": "3.1.1 Language of Page", "severity": "SERIOUS"}]
    vc.annotate_issues(issues, result)
    assert issues[0]["corroboration"]["failed_checks"] > 0


def test_annotate_issues_returns_same_list_object():
    result = vc.parse_fixture(_load("verapdf_rest_untagged.json"))
    issues = _make_issues()
    returned = vc.annotate_issues(issues, result)
    assert returned is issues


# ══ 6. LIVE integration — skipped unless Docker container is running ══════════════════════════════

@pytest.mark.skipif(
    not os.environ.get("ACP_VERAPDF_REST"),
    reason="ACP_VERAPDF_REST not set — set to a running verapdf/rest container to run live tests",
)
class TestLiveIntegration:
    """Live round-trip tests.  Require: docker run -d -p 8080:8080 verapdf/rest"""

    def _pdf_bytes(self, name: str) -> bytes:
        candidates = [
            Path(__file__).resolve().parent.parent / "demo-fixtures" / name,
            Path(__file__).resolve().parent.parent / "test-corpus" / "spike-fixtures" / name,
        ]
        for p in candidates:
            if p.exists():
                return p.read_bytes()
        pytest.skip(f"fixture not found: {name}")

    def test_live_untagged_pdf_is_not_compliant(self):
        pdf = self._pdf_bytes("pdf-accessibility-demo.pdf")
        r = vc.corroborate_pdf(pdf)
        assert r is not None
        assert r.compliant is False

    def test_live_untagged_pdf_corroborates_1_3_1(self):
        pdf = self._pdf_bytes("pdf-accessibility-demo.pdf")
        r = vc.corroborate_pdf(pdf)
        assert r is not None
        assert "1.3.1 Info and Relationships" in r.corroborates

    def test_live_untagged_pdf_corroborates_3_1_1(self):
        pdf = self._pdf_bytes("pdf-accessibility-demo.pdf")
        r = vc.corroborate_pdf(pdf)
        assert r is not None
        assert "3.1.1 Language of Page" in r.corroborates

    def test_live_form_fields_fixture(self):
        pdf = self._pdf_bytes("pdf-form-fields-spike.pdf")
        r = vc.corroborate_pdf(pdf)
        assert r is not None
        # Untagged form fixture fires 1.3.1 at minimum
        assert "1.3.1 Info and Relationships" in r.corroborates
