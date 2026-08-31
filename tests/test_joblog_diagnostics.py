"""The worker's crash diagnostics: flushed on emit, opaque about documents, per-document.

These pin the three properties that decide whether the log is usable after an exit-139, all of
which failed on 2026-08-30:

  FLUSHED. A SIGSEGV does not unwind and does not drain stdio buffers. Container stdout is
  block-buffered, so an unflushed line naming the document that killed the process is exactly
  the line that never arrives. Asserted by counting flushes, not by reading output — output
  proves the string was formatted, never that it left the buffer.

  FREE OF FILENAMES — these records, not the whole stream. Asserted by feeding a distinctive
  filename through and requiring it does not appear in what joblog wrote. The claim stops there
  on purpose: scanner.py still prints `[scan] analysing {name} …` to the same stdout, so the
  stream is NOT filename-free and saying otherwise would be a privacy claim the code does not
  support. Where an already-opaque id exists (a Drive file id) it is used as-is; the filename
  digest is a fallback and is a pseudonym, not anonymisation.

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


def test_doc_id_is_stable_and_short():
    a = joblog.doc_id(SENSITIVE)
    assert SENSITIVE not in a and "layoffs" not in a
    assert a == joblog.doc_id(SENSITIVE), (
        "must be stable across calls — 'this document was open on all three crashes' is only "
        "sayable if the same document yields the same id across attempts and restarts")
    assert len(a) == 14 and int(a[2:], 16) >= 0     # "h:" + 12 hex
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


# ── job identity survives threads ─────────────────────────────────────────────────────────────
# The per-document work runs one or two thread hops from worker.run_once
# (handlers._analyse_and_persist_one spawns a Thread, itself possibly inside a
# ThreadPoolExecutor). contextvars do NOT cross a thread start, so without joblog.bind() a stage
# record names a document and no job — which correlates nothing.

def test_job_identity_does_not_reach_a_plain_thread_without_bind():
    """The negative half. Stated as a test so the need for bind() is a measured fact rather than
    an assertion in a comment — if contextvars ever did propagate, this fails and bind() can go."""
    import threading as _t
    seen = {}
    with joblog.job_context(job_id="j1", attempt=2):
        def body():
            with recording_stdout() as cap:
                joblog.emit("stage.enter", stage="analyse.pdf", doc="d1")
                seen["rec"] = _records(cap)[0]
        th = _t.Thread(target=body)          # NOT bound
        th.start(); th.join()
    assert "job_id" not in seen["rec"]


def test_bind_carries_job_identity_into_a_thread():
    import threading as _t
    seen = {}
    with joblog.job_context(job_id="j1", attempt=2, scan_id="s1"):
        def body():
            with recording_stdout() as cap:
                joblog.emit("stage.enter", stage="analyse.pdf", doc="d1")
                seen["rec"] = _records(cap)[0]
        th = _t.Thread(target=joblog.bind(body))
        th.start(); th.join()
    rec = seen["rec"]
    assert rec["job_id"] == "j1" and rec["attempt"] == 2 and rec["scan_id"] == "s1"
    assert rec["doc"] == "d1"


def test_bind_carries_identity_through_TWO_nested_thread_hops():
    """The real shape: a pool thread that spawns another thread. Both hops must be bound, and
    binding at the inner hop alone would capture an already-empty context."""
    import threading as _t
    from concurrent.futures import ThreadPoolExecutor
    seen = {}
    with joblog.job_context(job_id="j9", attempt=3):
        def inner():
            with recording_stdout() as cap:
                joblog.emit("stage.enter", stage="analyse.ocr", doc="d2")
                seen["rec"] = _records(cap)[0]
        def outer():
            th = _t.Thread(target=joblog.bind(inner))
            th.start(); th.join()
        with ThreadPoolExecutor(max_workers=1) as ex:
            ex.submit(joblog.bind(outer)).result()
    assert seen["rec"]["job_id"] == "j9" and seen["rec"]["attempt"] == 3


def test_job_context_does_not_leak_after_the_block():
    with joblog.job_context(job_id="j1"):
        pass
    with recording_stdout() as cap:
        joblog.emit("stage.enter", stage="s", doc="d")
        rec = _records(cap)[0]
    assert "job_id" not in rec


def test_an_explicit_field_wins_over_the_ambient_context():
    with joblog.job_context(job_id="ambient"):
        with recording_stdout() as cap:
            joblog.emit("job.claim", job_id="explicit")
            rec = _records(cap)[0]
    assert rec["job_id"] == "explicit"


# ── document identity ─────────────────────────────────────────────────────────────────────────

def test_an_already_opaque_ref_is_preferred_over_hashing_the_filename():
    drive_id = "1AbCdEfGhIjKlMnOpQrStUvWxYz0123456"
    assert joblog.doc_id(SENSITIVE, opaque_ref=drive_id) == drive_id, (
        "a Drive file id is a real opaque handle and is already in the database — hashing it "
        "would only make correlation harder without making anything safer")


def test_the_filename_fallback_is_marked_as_a_digest_not_passed_off_as_an_id():
    d = joblog.doc_id(SENSITIVE)
    assert d.startswith("h:"), (
        "the fallback is a PSEUDONYM over a low-entropy name, not anonymisation; marking it "
        "keeps the two kinds of handle distinguishable in the log")
    assert SENSITIVE not in d and "layoffs" not in d
