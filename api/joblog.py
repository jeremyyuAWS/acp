"""Structured, immediately-flushed job diagnostics for the worker tier.

WHY THIS EXISTS. On 2026-08-30 the worker tier crashed natively — `free(): invalid next size
(normal)` at 2:42pm PDT, `free(): corrupted unsorted chunks` at 2:51pm, then Azure recording
exit 139 and restarts at 3:01, 3:12 and 3:23pm on revision acp-worker--0000467 — and the sweeper
dead-lettered discovery job db40880c03de4b89 as attempts-exhausted at 3:32:33pm. Which document
was open when the process died could not be established from the logs, because nothing recorded
it: `worker.py` printed a job id in exactly two places, a lease-overrun warning and a generic
loop error, and neither fires on a segfault.

Exit 139 is SIGSEGV. The process does not unwind, no `except` runs, no atexit hook runs, and
**anything still sitting in a buffer is gone**. Python's stdout is block-buffered when it is not
a TTY, which is exactly the case in a container, so the last several KB of diagnostics — the part
naming the document that killed it — is the part that never reaches the log. Every emit here is
therefore flushed on the spot. That single property is the reason this module exists rather than
a `logging` call: a handler that buffers is worse than no handler, because it looks like
instrumentation and produces nothing at the only moment it was needed.

WHAT IS AND IS NOT LOGGED. No filename, path, byte of content, token or signed URL appears in
these records. Documents are named by `doc`, which PREFERS an identifier the system already
treats as opaque — the Drive file id — and falls back to a digest of the filename only when no
such id reaches the call site.

BE PRECISE ABOUT WHAT THAT FALLBACK IS. A truncated unkeyed SHA-256 of a filename is a
PSEUDONYM, not anonymisation. Filenames are low-entropy and enumerable, so anyone holding the
digest and a candidate list can confirm a guess by hashing it; the digest resists casual reading,
not an adversary with the estate's file listing. It is used because it is stable and stops the
name being sitting in plain text, and it must not be described as anonymous or non-reversible.
The Drive id is preferred precisely because it is a real opaque handle rather than a disguised
name.

An operator maps `doc` back by recomputing it over the scan's own inventory rows, so the mapping
stays inside the system that already holds the filenames.

A CLAIM LINE ALONE IS NOT ENOUGH, which is the trap this module is shaped to avoid. One
discovery job walks a whole estate, so "job X was claimed" narrows a crash to a job that may
have touched thousands of documents. Correlation has to be per-document: `stage()` brackets each
native call with an enter and an exit.

WHAT AN UNMATCHED ENTER DOES AND DOES NOT MEAN. A document with an enter and no exit when the
log stops is a CRASH CANDIDATE — the work that was in flight. It is not proof that the document
is malformed, nor that the library named in the stage is the one that corrupted the heap: with a
12-slot pool a dozen documents are in flight at once, all of them unmatched, and only one of them
(at most) is implicated. The shortlist is where an investigation starts, not its conclusion.

CORRELATION SURVIVES THREADS, and has to. The per-document work does not run on the thread that
claimed the job: handlers._analyse_and_persist_one spawns a Thread, which may itself already be
inside a ThreadPoolExecutor, so the stage records are emitted one or two hops away from
worker.run_once. contextvars do NOT cross a thread boundary on their own, so `bind()` captures
the calling context and re-enters it inside the new thread. Without that the stage records carry
a document and no job, which correlates nothing.
"""
from __future__ import annotations

import contextvars
import functools
import hashlib
import json
import os
import sys
import threading
import time
import uuid
from contextlib import contextmanager

# Azure Container Apps injects both. Absent off-platform (local runs, CI, pytest), where the
# fallbacks keep every line well-formed rather than raising inside a diagnostic.
REVISION = os.environ.get("CONTAINER_APP_REVISION") or "unknown"
REPLICA = os.environ.get("CONTAINER_APP_REPLICA_NAME") or os.environ.get("HOSTNAME") or "unknown"
# Distinguishes two processes on the same replica, and survives a restart as a new value — so a
# gap in `proc` is itself the evidence that the container was replaced.
PROC = uuid.uuid4().hex[:8]

# `print()` writes the payload and the terminator as separate operations, so twelve pool threads
# emitting concurrently can interleave into unparseable half-lines. One locked write of a string
# that already carries its newline keeps each record whole.
_lock = threading.Lock()

# Set false by tests that assert on emission without polluting captured output; never in
# production, where the whole point is that the line reaches the container log.
_enabled = True


def doc_id(identifier: str | None, *, opaque_ref: str | None = None) -> str | None:
    """A stable handle for one document, preferring an id that is ALREADY opaque.

    `opaque_ref` is a system identifier that carries no user content — a Drive file id. When one
    is available it is used as-is: it is the real opaque handle, it already appears in the
    database, and hashing it would only make correlation harder for an operator without making
    anything safer.

    Falling back to a digest of `identifier` (the filename) yields a PSEUDONYM, not anonymity —
    see this module's header. Truncated to 12 hex (48 bits): collision-safe at estate scale and
    short enough to eyeball down a page of log lines.

    Deterministic either way, which is what makes "this document was open on all three crashes"
    a statement the log can support.
    """
    if opaque_ref:
        return str(opaque_ref)
    if identifier is None:
        return None
    return "h:" + hashlib.sha256(str(identifier).encode("utf-8", "replace")).hexdigest()[:12]


# The claimed job, for records emitted far from worker.run_once. A ContextVar rather than a
# threading.local so that `bind()` can carry it across a thread boundary explicitly; see the
# header on why that boundary exists at all.
_job_cv: contextvars.ContextVar[dict] = contextvars.ContextVar("acp_joblog_job", default={})


@contextmanager
def job_context(**fields):
    """Attach job identity to every record emitted inside this block, on any thread reached
    through `bind()`. Restores the previous value on exit, so nested jobs cannot leak."""
    token = _job_cv.set({k: v for k, v in fields.items() if v is not None})
    try:
        yield
    finally:
        _job_cv.reset(token)


def bind(fn):
    """Wrap `fn` so it runs inside the CURRENT context on whatever thread executes it.

    contextvars do not cross `threading.Thread` or `ThreadPoolExecutor.submit` — a new thread
    starts from an empty context, so a stage emitted there would carry a document and no job.
    Capturing at submit time and re-entering with `Context.run` is the supported way to carry it.
    """
    ctx = contextvars.copy_context()
    @functools.wraps(fn)
    def _run(*a, **kw):
        return ctx.run(fn, *a, **kw)
    return _run


def emit(event: str, **fields) -> None:
    """One structured record, on stdout, flushed before returning.

    Never raises. A diagnostic that can take the process down is worse than none, and this runs
    on the claim path of every job — so an unserialisable field degrades to its repr rather than
    propagating a TypeError into the worker loop.
    """
    if not _enabled:
        return
    rec = {"ts": time.time(), "event": event, "revision": REVISION,
           "replica": REPLICA, "proc": PROC}
    # Job identity from the ambient context first, so a record emitted deep inside a handler —
    # on a thread two hops from run_once — still says which job and which attempt it belongs to.
    # Explicit fields win, so a caller that knows better is never overwritten.
    try:
        rec.update({k: v for k, v in (_job_cv.get() or {}).items() if v is not None})
    except Exception:
        pass
    rec.update({k: v for k, v in fields.items() if v is not None})
    try:
        line = json.dumps(rec, default=repr)
    except Exception:
        line = json.dumps({"ts": time.time(), "event": event, "log_error": "unserialisable"})
    try:
        with _lock:
            sys.stdout.write(line + "\n")
            sys.stdout.flush()
    except Exception:
        pass


def _safe(event, **fields):
    """emit() that cannot alter the control flow of the work it observes. `stage()` wraps real
    document processing, so a fault in the logging path must not become the reason a document
    failed — the guarded call's own exception is the only one allowed out of here."""
    try:
        emit(event, **fields)
    except Exception:                                  # noqa: BLE001 — observation is never fatal
        pass


@contextmanager
def stage(name: str, *, job_id: str | None = None, doc: str | None = None, **fields):
    """Bracket one processing step — above all a native one — with an enter and an exit.

    The enter is flushed BEFORE the call it guards, which is the whole contract: a step that
    segfaults leaves an enter with no exit, and that asymmetry is the finding. The exit carries
    the elapsed seconds, so a step that is merely slow is distinguishable from one that died.

    Re-raises everything. This observes; it must not change which exceptions the worker's own
    retry policy sees.
    """
    _safe("stage.enter", stage=name, job_id=job_id, doc=doc, **fields)
    t0 = time.monotonic()
    try:
        yield
    except BaseException as exc:                       # noqa: BLE001 — observed, then re-raised
        _safe("stage.error", stage=name, job_id=job_id, doc=doc,
              elapsed_s=round(time.monotonic() - t0, 3),
              error_type=type(exc).__name__, **fields)
        raise
    else:
        _safe("stage.exit", stage=name, job_id=job_id, doc=doc,
              elapsed_s=round(time.monotonic() - t0, 3), **fields)
