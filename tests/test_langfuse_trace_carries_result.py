"""The per-file Langfuse trace carries the document + assessment RESULT as trace-level
input/output (not only on child spans), so the session list shows the outcome instead of
'no input or output' — while still carrying NO document content and NO raw filename
(docs/audit-langfuse-phi.md). Captures the payload that WOULD be sent, via a fake client, so
a future refactor that helpfully adds a free-text field is caught."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))
import lf  # noqa: E402


class _Trace:
    def __init__(self, sink, **kw):
        sink.append(kw)
        self._sink = sink

    def update(self, **kw):
        self._sink.append(kw)
        return self


class _Fake:
    def __init__(self):
        self.sent: list[dict] = []

    def trace(self, **kw):
        return _Trace(self.sent, **kw)


@pytest.fixture()
def cap(monkeypatch):
    f = _Fake()
    monkeypatch.setattr(lf, "_lf", lambda: f)
    monkeypatch.setattr(lf, "_PLAIN_FILENAMES", False, raising=False)  # redaction on, as in prod
    return f


def _blob(sent):
    return json.dumps(sent, default=str)


def test_file_trace_sets_document_and_format_input(cap):
    lf.file_trace("scan-1", "Q3 Budget.xlsx", user="dana@x.com")
    inp = cap.sent[0]["input"]
    assert inp["format"] == "xlsx"
    assert inp["document"].startswith("doc-")          # redacted label, not the real name
    assert "Q3 Budget" not in _blob(cap.sent)          # raw filename never sent


def test_assessment_result_lands_as_trace_output(cap):
    lf.file_assessment_result("scan-1", "Q3 Budget.xlsx", score=82.0, conformant=False,
                              level="AA", failing_criteria={"1.4.3": 3, "2.4.6": 1})
    out = next(p["output"] for p in cap.sent if "output" in p)
    assert out["score"] == 82.0
    assert out["conformant"] is False
    assert out["level"] == "AA"
    assert out["checks_failed"] == 2
    assert out["failing_criteria"] == {"1.4.3": 3, "2.4.6": 1}   # SC codes + counts
    assert out["findings_total"] == 4


def test_result_is_structured_only_no_free_text(cap):
    # A patient identifier could only reach the trace via a free-text field; there is none —
    # keys are WCAG codes, values are counts/score/boolean.
    lf.file_assessment_result("scan-1", "intake.docx", score=90, conformant=True,
                              level="AA", failing_criteria=None)
    out = next(p["output"] for p in cap.sent if "output" in p)
    assert out["failing_criteria"] == {} and out["checks_failed"] == 0 and out["findings_total"] == 0
    assert out["conformant"] is True and out["score"] == 90.0


def test_none_score_is_emitted_as_none_not_a_crash(cap):
    lf.file_assessment_result("scan-1", "a.pdf", score=None, conformant=True, level="A",
                              failing_criteria={})
    out = next(p["output"] for p in cap.sent if "output" in p)
    assert out["score"] is None


def test_extensionless_file_has_no_format_but_still_a_document(cap):
    lf.file_trace("scan-1", "README", user="x")
    inp = cap.sent[0]["input"]
    assert inp["format"] is None and inp["document"].startswith("doc-")
