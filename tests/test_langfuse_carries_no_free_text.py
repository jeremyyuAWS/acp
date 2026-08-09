"""No free text about a document leaves ACP in a Langfuse span (docs/audit-langfuse-phi.md).

The audit found `trace_hitl_decision` sending the reviewer's note verbatim and unbounded — the
only field in `api/lf.py` with neither a cap nor a schema, and the one most likely to contain a
patient, because it is free text typed by a human who is looking at the document.

These tests assert on the PAYLOAD THAT WOULD BE SENT, captured through a fake Langfuse client,
rather than on the shape of the call. A test that checked "the key is now note_chars" would pass
against a future version that helpfully added a `note_preview` beside it.

The prompt case is pinned alongside it. `trace_ai_call` has always sent `prompt_chars` rather
than the prompt, which is what makes ACP safe from the failure the backlog assumed it had — and
an untested invariant is one refactor from being untrue.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

import lf  # noqa: E402

SECRET = "Patient John Smith MRN 0114233 disputes the wording on page 4 of his discharge summary"


class _Span:
    def __init__(self, sink, **kw):
        sink.append(kw)
        self._sink = sink

    def end(self, **kw):
        self._sink.append(kw)
        return self


class _Trace:
    def __init__(self, sink, **kw):
        sink.append(kw)
        self._sink = sink

    def span(self, **kw):
        return _Span(self._sink, **kw)

    def update(self, **kw):
        self._sink.append(kw)
        return self


class _FakeLangfuse:
    """Captures every payload the module would hand to Langfuse."""

    def __init__(self):
        self.sent: list[dict] = []

    def trace(self, **kw):
        return _Trace(self.sent, **kw)

    def everything(self) -> str:
        return json.dumps(self.sent, default=str)

    def fields(self) -> list[dict]:
        """Every dict sent, plus the nested input/output/metadata blocks flattened out.

        The payloads arrive as `span(input={...}, output={...})`, so a top-level `.get("note")`
        looks clean while the note sits one level down — which is exactly the mistake that would
        make this whole file pass against unfixed code.
        """
        out: list[dict] = []
        for payload in self.sent:
            out.append(payload)
            for key in ("input", "output", "metadata"):
                nested = payload.get(key)
                if isinstance(nested, dict):
                    out.append(nested)
        return out


@pytest.fixture()
def captured(monkeypatch):
    fake = _FakeLangfuse()
    monkeypatch.setattr(lf, "_lf", lambda: fake)
    return fake


def test_the_reviewer_note_never_leaves_as_text(captured):
    """THE FINDING. The note's CONTENT must not appear anywhere in what is sent."""
    lf.trace_hitl_decision("scan-1", "intake.docx", "1.1.1", "rejected",
                           note=SECRET, approved_value="A chart of monthly premiums.")

    blob = captured.everything()
    assert SECRET not in blob, (
        "the reviewer's note was sent verbatim to Langfuse — it is free text about a patient "
        "document and must be reduced to a length, as prompts already are")
    # Not even a fragment: a preview would defeat the point, since a patient identifier sits at
    # the FRONT of a note like this one, not spread through it.
    assert "John Smith" not in blob and "0114233" not in blob


def test_the_length_is_still_reported(captured):
    """Bounded, not deleted — the span must still show a note existed and how long it was,
    which is what the observability was actually for."""
    lf.trace_hitl_decision("scan-1", "intake.docx", "1.1.1", "rejected", note=SECRET)

    assert any(p.get("note_chars") == len(SECRET) for p in captured.fields()), captured.fields()
    assert not any("note" in p for p in captured.fields()), (
        "'note' must be gone entirely, not carried alongside 'note_chars'")


def test_an_absent_note_reports_zero_not_none(captured):
    lf.trace_hitl_decision("scan-1", "intake.docx", "1.1.1", "approved", note=None)
    assert any(p.get("note_chars") == 0 for p in captured.fields())


def test_the_approved_value_is_still_sent_and_still_capped(captured):
    """Deliberately NOT reduced to a length. The approved value is the text ACP writes into the
    document, so seeing it is the point of tracing the decision at all — and unlike a free-text
    note it is a description of an image, authored to be published in the file. Capped, as it
    already was."""
    lf.trace_hitl_decision("scan-1", "intake.docx", "1.1.1", "approved",
                           approved_value="x" * 900)
    vals = [p.get("approved_value") for p in captured.fields() if p.get("approved_value")]
    assert vals and len(vals[0]) == 500


def test_prompts_are_still_sent_as_a_length_only(captured):
    """The invariant the whole Langfuse audit turned on, now pinned.

    ACP does not use Langfuse auto-instrumentation; it hand-builds spans and sends a count. That
    is why document text and OCR output never leave. Nothing tested it before.
    """
    prompt = "Describe this image. Context: " + SECRET
    lf.trace_ai_call("describe_image", "moondream", 1200, ok=True,
                     prompt_chars=len(prompt), completion="A bar chart.",
                     scan_id="scan-1", file="intake.docx")

    blob = captured.everything()
    assert SECRET not in blob, "the prompt reached Langfuse — it may carry document text or OCR"
    assert any(p.get("prompt_chars") == len(prompt) for p in captured.fields())


def test_nothing_is_sent_at_all_when_tracing_is_disabled(monkeypatch):
    """The other half of the guarantee: absent credentials means no tracing, not partial."""
    monkeypatch.setattr(lf, "_lf", lambda: None)
    # Must not raise, and must reach no client.
    lf.trace_hitl_decision("scan-1", "intake.docx", "1.1.1", "rejected", note=SECRET)
    lf.trace_ai_call("describe_image", "moondream", 1, ok=True, completion=SECRET)
