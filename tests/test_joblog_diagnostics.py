"""The worker's crash diagnostics: flushed on emit, opaque about documents, per-document.

These pin the three properties that decide whether the log is usable after an exit-139, all of
which failed on 2026-08-30:

  FLUSHED. A SIGSEGV does not unwind and does not drain stdio buffers. Container stdout is
  block-buffered, so an unflushed line naming the document that killed the process is exactly
  the line that never arrives. Asserted by counting flushes, not by reading output — output
  proves the string was formatted, never that it left the buffer.

  OPAQUE. Filenames are disclosure in their own right, and these records go to a log stream with
  a different audience and retention from the database. Asserted by feeding a distinctive
  filename through and requiring it does not appear anywhere in what was written.

  PER-DOCUMENT. One discovery job walks a whole estate, so a claim line narrows a crash to a job
  that touched thousands of documents. The enter/exit asymmetry is what shortlists the candidate,
  so the enter must be emitted BEFORE the guarded call, not after it returns.
"""
from __future__ import annotations

import io
import json
import sys
from contextlib import contextmanager

import pytest

sys.path.insert(0, "api")
import joblog  # noqa: E402


class _CountingStream(io.StringIO):
    """Records the ORDER of writes and flushes. A test that only reads the final buffer cannot
    tell a flushed write from a buffered one, which is the single property that matters here."""

    def __init__(self):
        super().__init__()
        self.events = []

    def write(self, s):
        self.events.append(("write", s))
        return super().write(s)

    def flush(self):
        self.events.append(("flush", None))
        return super().flush()


@contextmanager
def recording_stdout():
    """Swap sys.stdout for a stream that records write/flush ORDER.

    Deliberately a context manager used INSIDE the test body, not a fixture, and that is not a
    style choice. A `monkeypatch.setattr(sys, "stdout", ...)` applied during FIXTURE SETUP does
    not survive into the test: pytest suspends its capture around fixture setup and reinstalls
    its own capture object on resume, discarding the patch with no error. Measured while writing
    these — the fixture form reported `sys.stdout is cap` as False and collected zero events, so
    every assertion below would have run against an empty list. `test_every_emit_is_flushed…`
    caught it by asserting on a non-empty sequence; a test asserting only "no filename appears"
    would have passed on a stream nothing was ever written to, which is the shape of a check that
    cannot fail. Restoring by hand in a finally keeps the swap inside the body, where it sticks.
    """
    prev = sys.stdout
    stream = _CountingStream()
    sys.stdout = stream
    try:
        yield stream
    finally:
        sys.stdout = prev


def _records(stream):
    return [json.loads(s) for kind, s in stream.events if kind == "write" and s.strip()]


# ── flushed ───────────────────────────────────────────────────────────────────────────────────

def test_every_emit_is_flushed_before_it_returns():
    with recording_stdout() as cap:
        joblog.emit("job.claim", job_id="j1")
        kinds = [k for k, _ in cap.events]
    assert kinds == ["write", "flush"], (
        "a record must be flushed by the time emit() returns — a buffered diagnostic is lost "
        f"to the SIGSEGV it exists to explain; saw {kinds}")


def test_stage_flushes_the_enter_before_running_the_guarded_call():
    """The ordering IS the contract. If the enter were emitted after the call returned, a
    segfaulting call would leave no trace at all and the shortlist would be empty."""
    with recording_stdout() as cap:
        seen_at_call_time = []
        with joblog.stage("analyse.pdf", doc="abc123"):
            seen_at_call_time.extend(_records(cap))
        first_two = cap.events[:2]

    assert [r["event"] for r in seen_at_call_time] == ["stage.enter"], (
        "the enter must already be written and flushed while the guarded call is running")
    assert ("flush", None) in first_two


def test_a_stage_that_dies_leaves_an_enter_with_no_exit():
    """The asymmetry a crash produces, simulated with an exception. A real SIGSEGV emits nothing
    further at all, which is why the enter has to stand on its own as the evidence."""
    with recording_stdout() as cap:
        with pytest.raises(RuntimeError):
            with joblog.stage("analyse.ocr", doc="deadbeef"):
                raise RuntimeError("boom")
        events = [r["event"] for r in _records(cap)]

    assert events == ["stage.enter", "stage.error"]
    assert "stage.exit" not in events


def test_stage_reraises_rather_than_swallowing():
    """Observation must not change which exceptions the retry policy sees."""
    class Marker(Exception):
        pass

    with recording_stdout():
        with pytest.raises(Marker):
            with joblog.stage("analyse.text", doc="d"):
                raise Marker()


def test_a_completed_stage_records_its_elapsed_time():
    with recording_stdout() as cap:
        with joblog.stage("analyse.office", doc="d"):
            pass
        recs = _records(cap)

    exit_rec = [r for r in recs if r["event"] == "stage.exit"][0]
    assert isinstance(exit_rec["elapsed_s"], (int, float)), (
        "a slow step and a dead step are different findings; the exit carries the duration "
        "that tells them apart")


# ── opaque ────────────────────────────────────────────────────────────────────────────────────

SENSITIVE = "Q3-layoffs-confidential.docx"


def test_doc_id_is_opaque_stable_and_short():
    a = joblog.doc_id(SENSITIVE)
    assert SENSITIVE not in a and "layoffs" not in a
    assert a == joblog.doc_id(SENSITIVE), (
        "must be stable across calls — 'this document was open on all three crashes' is only "
        "sayable if the same document yields the same id across attempts and restarts")
    assert len(a) == 12 and int(a, 16) >= 0
    assert joblog.doc_id("other.docx") != a
    assert joblog.doc_id(None) is None


def test_no_filename_reaches_the_log_through_a_stage():
    with recording_stdout() as cap:
        with joblog.stage("analyse.pdf", doc=joblog.doc_id(SENSITIVE), ext=".docx"):
            pass
        written = "".join(s for k, s in cap.events if k == "write")

    assert written, "nothing was captured — the assertions below would be vacuous"
    assert SENSITIVE not in written and "layoffs" not in written
    assert joblog.doc_id(SENSITIVE) in written, "the opaque handle must still be there to correlate"


# ── never breaks the worker ───────────────────────────────────────────────────────────────────

def test_an_unserialisable_field_does_not_raise():
    """This runs on the claim path of every job. A diagnostic that can take the process down is
    worse than none at all."""
    class Weird:
        def __repr__(self):
            return "<weird>"

    with recording_stdout() as cap:
        joblog.emit("job.claim", job_id="j1", thing=Weird())
        recs = _records(cap)

    assert recs[0]["thing"] == "<weird>"


def test_a_broken_stdout_does_not_raise():
    class Broken:
        def write(self, s):
            raise OSError("stream closed")

        def flush(self):
            raise OSError("stream closed")

    prev = sys.stdout
    sys.stdout = Broken()
    try:
        joblog.emit("job.claim", job_id="j1")          # must not raise
    finally:
        sys.stdout = prev


def test_records_carry_the_replica_identity():
    with recording_stdout() as cap:
        joblog.emit("job.claim", job_id="j1")
        recs = _records(cap)

    for key in ("ts", "event", "revision", "replica", "proc"):
        assert key in recs[0], f"{key} is needed to tie a crash to the replica and revision it hit"
