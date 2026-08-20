"""The trace NAME is the label shown in Langfuse's trace/session LIST — a wider-access surface
than the app — and it must not lead with the operator's email. It used to:
`jeremy_acp@…onmicrosoft.com · doc-…`, on every file, scan, assess and discover trace. That is an
identity leak, distinct from the PHI (filename) guards: the operator email is not a patient name,
but it still has no business in a shared observability list. Segregation BY operator stays
available through `user_id` and the `user:` tag (both filterable), which SHOULD keep the email.

Also pins two logging-legibility improvements shipped with the fix: a `format:` tag so the native
UI can filter by document type, and the verdict-in-name upgrade so the list reads at a glance."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))
import lf  # noqa: E402

EMAIL = "jeremy_acp@fgxlxj.onmicrosoft.com"


class _Trace:
    def __init__(self, sink, **kw):
        sink.append(("trace", kw))
        self._sink = sink

    def update(self, **kw):
        self._sink.append(("update", kw))
        return self

    def span(self, **kw):
        self._sink.append(("span", kw))
        return self


class _Fake:
    def __init__(self):
        self.calls: list = []

    def trace(self, **kw):
        return _Trace(self.calls, **kw)


@pytest.fixture()
def cap(monkeypatch):
    f = _Fake()
    monkeypatch.setattr(lf, "_lf", lambda: f)
    monkeypatch.setattr(lf, "_PLAIN_FILENAMES", False, raising=False)
    return f

def _names(cap):
    return [kw.get("name") for kind, kw in cap.calls if "name" in kw]


def test_file_trace_name_carries_no_operator_email(cap):
    lf.file_trace("scan-1", "Intake.docx", user=EMAIL)
    names = _names(cap)
    assert names, "file_trace set no name"
    for n in names:
        assert EMAIL not in n
        assert "@" not in n                      # no email in any name
    # but the operator is STILL filterable — user_id and a user: tag carry it
    tkw = next(kw for kind, kw in cap.calls if kind == "trace")
    assert tkw.get("user_id") == EMAIL
    assert any(str(t) == f"user:{EMAIL}" for t in (tkw.get("tags") or []))


def test_file_trace_tags_include_format_for_filtering(cap):
    lf.file_trace("scan-1", "Q3 Budget.xlsx", user=EMAIL)
    tkw = next(kw for kind, kw in cap.calls if kind == "trace")
    assert "format:xlsx" in (tkw.get("tags") or [])


def test_assessment_result_upgrades_the_name_with_the_verdict_no_email(cap):
    lf.file_assessment_result("scan-1", "Intake.docx", score=82.0, conformant=False, level="AA",
                              failing_criteria={"1.4.3": 2})
    upd = next(kw for kind, kw in cap.calls if kind == "update")
    name = upd.get("name")
    assert name and "@" not in name
    assert name.startswith("doc-") and "✗ AA" in name    # verdict + level, no identity
    lf.file_assessment_result("scan-1", "Clean.pdf", score=100, conformant=True, level="AA")
    ok = [kw for kind, kw in cap.calls if kind == "update"][-1]
    assert "✓ AA" in ok.get("name") and "@" not in ok.get("name")


def test_discover_run_trace_name_carries_no_email(cap):
    lf.discover_run_trace("scan-1", source="local", listed=44, inventoried=44, user=EMAIL)
    blob = json.dumps([n for n in _names(cap)], default=str)
    assert EMAIL not in blob and "@" not in blob
