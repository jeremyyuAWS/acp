"""A patient's name must not reach Langfuse via the filename (docs/audit-langfuse-phi.md, P0.10).

`Smith_John_MRN0114233_intake.docx` names a patient, and the filename was the one field riding on
EVERY trace — name, id, tag and metadata — on every scan, whether or not a model ran. It was the
largest exposure by volume in that audit and the least obvious, because nobody thinks of a
filename as content.

WHY THIS FILE SWEEPS EVERY ENTRY POINT rather than testing the helper. `_doc_label` in isolation
is trivially correct; the risk is a CALL SITE that forgot it. There were nine, across four kinds
of field (span name, trace id, tag, metadata), and the trace id was the one most likely to be
missed — redacting the display while `id=f"{scan_id}::{file}"` still carries the name would look
fixed and change nothing. So each test drives a real public function and asserts the patient's
name appears nowhere in what would be sent.
"""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

PATIENT = "Smith_John_MRN0114233_intake.docx"
SCAN = "a242d0f5f635"


class _Node:
    def __init__(self, sink, **kw):
        sink.append(kw)
        self._sink = sink

    def span(self, **kw):
        return _Node(self._sink, **kw)

    def update(self, **kw):
        self._sink.append(kw)
        return self

    def end(self, **kw):
        self._sink.append(kw)
        return self


class _FakeLangfuse:
    def __init__(self):
        self.sent: list[dict] = []

    def trace(self, **kw):
        return _Node(self.sent, **kw)

    def score(self, **kw):
        self.sent.append(kw)

    def everything(self) -> str:
        return json.dumps(self.sent, default=str)


@pytest.fixture()
def lf_mod(monkeypatch):
    """lf with redaction ON (the default) and a fixed salt, plus a capturing client."""
    monkeypatch.setenv("ACP_TRACE_SALT", "unit-test-salt")
    monkeypatch.delenv("ACP_TRACE_FILENAMES", raising=False)
    import lf as _lf
    mod = importlib.reload(_lf)
    fake = _FakeLangfuse()
    monkeypatch.setattr(mod, "_lf", lambda: fake)
    mod._captured = fake
    return mod


def _clean(mod, *, allow_ext=True):
    blob = mod._captured.everything()
    assert "Smith_John" not in blob and "MRN0114233" not in blob and PATIENT not in blob, (
        f"the filename reached Langfuse: {blob[:400]}")
    return blob


# ── every entry point that takes a filename ──────────────────────────────────

def test_file_trace_redacts_name_id_and_tags(lf_mod):
    lf_mod.file_trace(SCAN, PATIENT, user="nurse@hospital.org")
    blob = _clean(lf_mod)
    assert "doc-" in blob, "the document must still be identifiable by a stable label"


def test_the_trace_id_itself_is_redacted(lf_mod):
    """THE ONE MOST LIKELY TO BE MISSED. The id joins a file's spans, its AI calls, its HITL
    decisions and its score; it used to interpolate the raw filename at four separate sites.
    Redacting the display and leaving the id would look fixed and leak exactly as before."""
    tid = lf_mod._trace_id(SCAN, PATIENT)
    assert PATIENT not in tid and "Smith_John" not in tid
    assert tid.startswith(f"{SCAN}::doc-")


def test_file_span_and_rule_spans_redact(lf_mod):
    trace = lf_mod.file_trace(SCAN, PATIENT, user="nurse@hospital.org")
    span = lf_mod.file_span(trace, PATIENT, "docx")
    lf_mod.rule_spans(span, {"1.1.1": 2}, [{"id": "1.1.1", "plain": "Non-text Content"}],
                      filename=PATIENT, scan_id=SCAN, user="nurse@hospital.org")
    _clean(lf_mod)


def test_pii_span_redacts(lf_mod):
    trace = lf_mod.file_trace(SCAN, PATIENT, user="n@h.org")
    span = lf_mod.file_span(trace, PATIENT, "docx")
    lf_mod.pii_span(span, {"types": {"ssn": 3}}, filename=PATIENT)
    _clean(lf_mod)


def test_ai_and_hitl_and_score_redact(lf_mod):
    lf_mod.trace_ai_call("describe_image", "moondream", 900, ok=True,
                         prompt_chars=120, completion="A bar chart.",
                         scan_id=SCAN, file=PATIENT)
    lf_mod.trace_hitl_decision(SCAN, PATIENT, "1.1.1", "approved", approved_value="A bar chart.")
    lf_mod.file_score(SCAN, PATIENT, 91.0)
    _clean(lf_mod)


# ── the properties that make the label worth having ──────────────────────────

def test_the_label_is_stable_so_a_document_stays_followable(lf_mod):
    """Every span for one document must still collapse onto one trace."""
    assert lf_mod._doc_label(PATIENT) == lf_mod._doc_label(PATIENT)
    assert lf_mod._trace_id(SCAN, PATIENT) == lf_mod._trace_id(SCAN, PATIENT)
    assert lf_mod._doc_label(PATIENT) != lf_mod._doc_label("other_patient_intake.docx")


def test_the_extension_survives_because_a_type_is_not_an_identifier(lf_mod):
    assert lf_mod._doc_label(PATIENT).endswith(".docx")
    assert lf_mod._doc_label("scan.PDF").endswith(".pdf")


def test_a_dotted_name_does_not_leak_a_word_as_an_extension(lf_mod):
    """"Smith, John. Intake" would naively yield an "extension" of " Intake" — part of the
    patient's own name, pasted straight back into the label the redaction just built."""
    label = lf_mod._doc_label("Smith, John. Intake")
    assert "Intake" not in label and "John" not in label, label


def test_the_label_is_keyed_not_a_plain_digest(lf_mod, monkeypatch):
    """An unkeyed digest is a dictionary: anyone who suspects a patient is in the estate could
    hash the likely filename and confirm it. Changing the salt must change the label."""
    first = lf_mod._doc_label(PATIENT)
    monkeypatch.setenv("ACP_TRACE_SALT", "a-different-deployment")
    import lf as _lf
    assert importlib.reload(_lf)._doc_label(PATIENT) != first


def test_none_stays_none(lf_mod):
    """Several callers pass an optional filename and gate on it; "None" would be a fake document."""
    assert lf_mod._doc_label(None) is None
    assert lf_mod._doc_label("") == ""
    assert lf_mod._trace_id(SCAN, None) is None


# ── the opt-out, and its direction ───────────────────────────────────────────

def test_plain_mode_restores_readable_filenames_for_the_demo(monkeypatch):
    monkeypatch.setenv("ACP_TRACE_FILENAMES", "plain")
    import lf as _lf
    mod = importlib.reload(_lf)
    assert mod._doc_label(PATIENT) == PATIENT


def test_redaction_is_the_DEFAULT_not_the_opt_in(monkeypatch):
    """The load-bearing direction. A deployment that sets nothing must be the SAFE one — the cost
    of the wrong default is asymmetric: an inconvenient demo versus patient names in an
    observability store. An unrecognised value must also fail safe, not fall through to plain."""
    monkeypatch.delenv("ACP_TRACE_FILENAMES", raising=False)
    import lf as _lf
    assert importlib.reload(_lf)._doc_label(PATIENT) != PATIENT

    for junk in ("true", "1", "yes", "PLAIN ", "plaintext"):
        monkeypatch.setenv("ACP_TRACE_FILENAMES", junk)
        got = importlib.reload(_lf)._doc_label(PATIENT)
        if junk.strip().lower() == "plain":
            continue
        assert got != PATIENT, f"{junk!r} must not enable plain filenames"


@pytest.fixture(autouse=True)
def _restore_module_state():
    """lf caches env at import, and these tests reload it. Leave the real module behind for
    everything else in the suite."""
    yield
    import lf as _lf
    importlib.reload(_lf)
