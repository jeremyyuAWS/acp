"""Two Langfuse-logging P1 items:

  1. every trace is stamped with an ENVIRONMENT (production / staging / demo) so a shared project's
     traces separate instead of mingling under "default" — set on the SDK client from ACP_ENV;
  2. file traces carry OUTCOME tags (result:fail|needs-review|pass, pii:flagged) so the native list
     filters by result, not only by document/format.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))
import lf  # noqa: E402
import handlers  # noqa: E402


# ── item 1: environment on the client ─────────────────────────────────────────
def test_env_is_sanitised_to_langfuse_safe_chars():
    # module-level _ENV is lowercase and only [a-z0-9_-] (a stray value can't make the client 400)
    assert lf._ENV and lf._ENV == lf._re.sub(r"[^a-z0-9_-]", "-", lf._ENV.lower())


def test_client_is_constructed_with_the_environment(monkeypatch):
    captured = {}

    class _FakeLangfuse:
        def __init__(self, **kw):
            captured.update(kw)

    import langfuse
    monkeypatch.setattr(langfuse, "Langfuse", _FakeLangfuse)
    monkeypatch.setattr(lf, "_ENABLED", True, raising=False)
    monkeypatch.setattr(lf, "_ENV", "staging", raising=False)
    monkeypatch.setattr(lf, "_client", None, raising=False)
    lf._lf()
    assert captured.get("environment") == "staging"


def test_client_falls_back_when_the_sdk_rejects_environment(monkeypatch):
    seen = {"calls": 0}

    class _OldLangfuse:
        def __init__(self, **kw):
            seen["calls"] += 1
            if "environment" in kw:
                raise TypeError("unexpected keyword 'environment'")

    import langfuse
    monkeypatch.setattr(langfuse, "Langfuse", _OldLangfuse)
    monkeypatch.setattr(lf, "_ENABLED", True, raising=False)
    monkeypatch.setattr(lf, "_client", None, raising=False)
    assert lf._lf() is not None            # constructed via the fallback, didn't raise
    assert seen["calls"] == 2              # tried with environment, then without


# ── item 2: outcome tags ──────────────────────────────────────────────────────
class _Trace:
    def __init__(self, sink):
        self._sink = sink

    def update(self, **kw):
        self._sink.append(kw)
        return self


class _Fake:
    def __init__(self):
        self.sink = []

    def trace(self, **kw):
        return _Trace(self.sink)


@pytest.fixture()
def cap(monkeypatch):
    f = _Fake()
    monkeypatch.setattr(lf, "_lf", lambda: f)
    monkeypatch.setattr(lf, "_PLAIN_FILENAMES", False, raising=False)
    return f


def test_outcome_tags_carry_result_pii_and_the_base_tags(cap):
    lf.set_outcome_tags("scan-1", "Intake.docx", "nurse@x", result="fail",
                        pii_flagged=True, failing_rule_ids=["1.4.3", "1.1.1"])
    tags = cap.sink[0]["tags"]
    assert "result:fail" in tags and "pii:flagged" in tags
    assert "accessibility-file" in tags and "format:docx" in tags   # base tags re-included
    assert "rule-fail:1.4.3" in tags and "rule-fail:1.1.1" in tags   # per-rule tags preserved
    # the operator stays available as a filterable user: tag (that's by design, unlike the NAME)
    assert "user:nurse@x" in tags


def test_outcome_tags_omit_pii_when_not_flagged(cap):
    lf.set_outcome_tags("scan-1", "clean.pdf", "u", result="pass")
    tags = cap.sink[0]["tags"]
    assert "result:pass" in tags and "pii:flagged" not in tags


# ── the result label _emit_file_assess derives ────────────────────────────────
@pytest.fixture()
def cap_tags(monkeypatch):
    """Capture the result label _emit_file_assess passes to set_outcome_tags."""
    seen = {}
    monkeypatch.setattr(lf, "file_trace", lambda *a, **k: object())
    monkeypatch.setattr(lf, "assess_span", lambda *a, **k: _Noop())
    monkeypatch.setattr(lf, "rule_spans", lambda *a, **k: None)
    monkeypatch.setattr(lf, "file_score", lambda *a, **k: None)
    monkeypatch.setattr(lf, "file_assessment_result", lambda *a, **k: None)
    monkeypatch.setattr(lf, "set_outcome_tags",
                        lambda sid, f, u, **k: seen.update(k))
    return seen


class _Noop:
    def end(self, **k):
        return self


def test_result_label_is_fail_review_pass(cap_tags):
    handlers._emit_file_assess("s", "f.docx", "AA", sc_counts={"1.4.3": 2}, outcomes={"FAIL": 1},
                               conformant=False, score=40, pii_payload=None, remediation={})
    assert cap_tags["result"] == "fail"

    handlers._emit_file_assess("s", "f.docx", "AA", sc_counts={}, outcomes={"REVIEW": 1, "PASS": 5},
                               conformant=True, score=90, pii_payload=None, remediation={})
    assert cap_tags["result"] == "needs-review"

    handlers._emit_file_assess("s", "f.docx", "AA", sc_counts={}, outcomes={"PASS": 6},
                               conformant=True, score=100, pii_payload={"flagged": False}, remediation={})
    assert cap_tags["result"] == "pass"
