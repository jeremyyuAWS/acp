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

    def generation(self, **kw):
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
            for key in ("input", "output", "metadata", "usage"):
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


DISPOSITION_DETAIL = (
    "queued by policy 'Archive intake for John Smith MRN 0114233' — awaiting approval")


def test_disposition_decision_reason_never_leaves_as_text(captured):
    """N2. The disposition surface (the pending-approval queue, #360) now traces its decisions.
    Its `detail` is free text — a policy NAME, a Drive error, a doc id spliced into a sentence —
    with no cap and no schema, so it must be reduced to a length, never sent verbatim."""
    lf.trace_disposition_decision("drive:1a2b3c", "intake.docx", action="archive",
                                  status="pending_approval", policy_id="p2",
                                  reason=DISPOSITION_DETAIL)
    blob = captured.everything()
    assert DISPOSITION_DETAIL not in blob, (
        "the disposition detail reached Langfuse verbatim — it is free text that can carry a "
        "patient (a policy name, a note) and must be reduced to a length")
    assert "John Smith" not in blob and "0114233" not in blob


def test_disposition_decision_reports_status_ids_and_reason_length(captured):
    """Bounded, not deleted: the span still shows the action, status, policy id and how long the
    reason was — status/counts/redacted ids only, which is what the observability was for."""
    lf.trace_disposition_decision("drive:1a2b3c", "intake.docx", action="archive",
                                  status="rejected", policy_id="p2", reason=DISPOSITION_DETAIL)
    fields = captured.fields()
    assert any(p.get("reason_chars") == len(DISPOSITION_DETAIL) for p in fields), fields
    assert not any("reason" in p for p in fields), (
        "'reason' must be gone entirely, not carried alongside 'reason_chars'")
    assert any(p.get("status") == "rejected" for p in fields)
    assert any(p.get("action") == "archive" and p.get("policy_id") == "p2" for p in fields)


def test_disposition_decision_absent_reason_reports_zero(captured):
    lf.trace_disposition_decision("drive:1a2b3c", "intake.docx", action="leave",
                                  status="approved", policy_id="p3", reason=None)
    assert any(p.get("reason_chars") == 0 for p in captured.fields())


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


def test_ai_generation_carries_model_tokens_cost_zone_but_no_text(captured):
    """G1+G3. The model call is now a GENERATION carrying model / token usage / cost / provider /
    zone — the LLM-native fields Langfuse rolls up — and STILL no prompt or completion text."""
    prompt = "Describe this image. Context: " + SECRET
    completion = "A bar chart of " + SECRET
    lf.trace_ai_call("vision", "llava:7b", 1500, ok=True,
                     prompt_chars=len(prompt), completion=completion,
                     scan_id="scan-1", file="intake.docx",
                     provider="azure_openai", zone="cloud", cost=0.0123,
                     prompt_tokens=312, completion_tokens=48)

    blob = captured.everything()
    assert SECRET not in blob, "prompt/completion text reached Langfuse via the generation"

    fields = captured.fields()
    # A generation payload names the model at the top level (that is what makes it a generation,
    # not a span) — assert the LLM-native fields are all present.
    assert any(p.get("model") == "llava:7b" for p in fields), fields
    assert any(p.get("input") == 312 and p.get("output") == 48 for p in fields), (
        "token usage must reach the generation (usage.input / usage.output)")
    assert any(p.get("total_cost") == 0.0123 for p in fields), "cost must reach the generation"
    assert any(p.get("provider") == "azure_openai" and p.get("zone") == "cloud" for p in fields)
    # Sizes are still there as counts, never the strings.
    assert any(p.get("prompt_chars") == len(prompt) for p in fields)
    assert any(p.get("completion_chars") == len(completion) for p in fields)


def test_ai_generation_nests_under_the_file_trace(captured):
    """G2. When scan_id + file are known the generation hangs on the file's OWN trace id
    (`{scan_id}::{doc-label}`), not a detached top-level `ai:` trace — so a document's model
    calls live in its story. The trace id must carry the REDACTED label, never the filename."""
    lf.trace_ai_call("vision", "llava:7b", 100, ok=True, prompt_chars=10,
                     completion="x", scan_id="scan-9", file="intake.docx")
    tid = lf._trace_id("scan-9", "intake.docx")
    assert any(p.get("id") == tid for p in captured.sent), (
        f"generation did not nest on the file trace {tid!r}: {captured.sent}")
    # session grouping preserved so the scan's session view still gathers this call.
    assert any(p.get("session_id") == "scan-9" for p in captured.sent)


def test_ai_call_without_a_file_falls_back_to_a_session_grouped_trace(captured):
    """G2 fallback. A request-path call with no file (e.g. the changelog digest) still traces —
    as a per-call `ai:{surface}` trace grouped into the session — rather than being dropped."""
    lf.trace_ai_call("digest", "qwen3", 50, ok=True, prompt_chars=5,
                     completion="y", scan_id="scan-7")
    assert any(p.get("name") == "ai:digest" and p.get("session_id") == "scan-7"
               for p in captured.sent), captured.sent


def test_remediation_span_carries_counts_and_no_text(captured):
    """G4. The Remediate span reports how many fixes applied / skipped — COUNTS only. No
    filename, no per-fix prose, no reviewer text."""
    trace = lf.file_trace("scan-1", "intake.docx", user="nurse@hospital.org")
    lf.remediate_span(trace, "https://drive/xyz", fixes_applied=4, fixes_skipped=2,
                      per_rule={"1.1.1": 3, "2.4.4": 1})
    fields = captured.fields()
    assert any(p.get("fixes_applied") == 4 and p.get("fixes_skipped") == 2 for p in fields), fields
    assert any(p.get("fixes_by_rule") == {"1.1.1": 3, "2.4.4": 1} for p in fields)
    # No document content: the applied/skipped MESSAGES ("3 images: added alt text") are prose and
    # must not ride the span, and neither may the filename.
    blob = captured.everything()
    assert "intake.docx" not in blob and "added alt text" not in blob


def test_cloud_vision_generation_carries_real_usage_from_the_adapter(captured, monkeypatch):
    """N1 (Langfuse audit new-feature bucket). A cloud vision escalation must reach Langfuse as a
    GENERATION carrying the REAL token usage the provider measured — not the zeros/None the cloud
    path emitted before this change, when the counts were computed for cost and then dropped on the
    trace side. Driven end-to-end through ai._escalate_vision so the wiring, not just lf, is proven.

    Still numbers only: the prompt and the model's answer both carry a patient identifier here, and
    neither may appear in what is sent (docs/audit-langfuse-phi.md)."""
    import types
    sys.path.insert(0, str(ACP / "api"))
    import ai
    import providers

    prompt = "Describe this chart. Context: " + SECRET
    answer = "A bar chart of " + SECRET

    class _FakeCloud:
        name = "anthropic"
        zone = "cloud"

        def generate(self, prompt, image_bytes, *, model=None, timeout=120.0):
            # The shape a real cloud adapter now returns: cost AND token usage measured together.
            return {"text": answer, "model": "claude-opus-4-8", "provider": "anthropic",
                    "zone": "cloud", "latency_ms": 900, "ok": True, "cost_usd": 0.0123,
                    "reason": providers.REASON_OK,
                    "prompt_tokens": 312, "completion_tokens": 48}

    monkeypatch.setattr(providers, "cloud_vision_provider", lambda: _FakeCloud())

    out = ai._escalate_vision(prompt, b"IMGBYTES", scan_id="scan-1", file="intake.docx")
    assert out is not None and out["provider"] == "anthropic"

    blob = captured.everything()
    assert SECRET not in blob, "prompt/completion text reached Langfuse via the cloud generation"
    assert "John Smith" not in blob and "0114233" not in blob

    fields = captured.fields()
    assert any(p.get("model") == "claude-opus-4-8" for p in fields), fields
    # The whole point of N1: the generation's usage carries the adapter's REAL counts, not 0/None.
    assert any(p.get("input") == 312 and p.get("output") == 48 for p in fields), (
        "cloud-vision token usage did not reach the Langfuse generation (usage.input/output)")
    assert any(p.get("total_cost") == 0.0123 for p in fields)
    assert any(p.get("provider") == "anthropic" and p.get("zone") == "cloud" for p in fields)


def test_nothing_is_sent_at_all_when_tracing_is_disabled(monkeypatch):
    """The other half of the guarantee: absent credentials means no tracing, not partial."""
    monkeypatch.setattr(lf, "_lf", lambda: None)
    # Must not raise, and must reach no client.
    lf.trace_hitl_decision("scan-1", "intake.docx", "1.1.1", "rejected", note=SECRET)
    lf.trace_disposition_decision("drive:1a2b3c", "intake.docx", action="archive",
                                  status="pending_approval", policy_id="p2",
                                  reason=DISPOSITION_DETAIL)
    lf.trace_ai_call("describe_image", "moondream", 1, ok=True, completion=SECRET,
                     prompt_tokens=1, completion_tokens=1, cost=0.5)
    # generation() and remediate_span() are no-ops on a _Noop trace, so they never touch a client.
    assert isinstance(lf.generation(lf._Noop(), "vision", model="m"), lf._Noop)
    lf.remediate_span(lf._Noop(), "https://drive/xyz", fixes_applied=1, fixes_skipped=0)
