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

WHAT IS AND IS NOT LOGGED. Document identity is recorded as an opaque `doc` — the first 12 hex
of a SHA-256 over the document's stable identifier — never a filename, path, byte of content,
token or signed URL. These lines go to a container log stream with a different audience and
retention from the application database, and a filename is itself disclosure: "Q3-layoffs.docx"
names the thing whether or not anyone opens it.

An operator maps `doc` back by recomputing it over the scan's own inventory rows
(`joblog.doc_id(<the same identifier>)`) — the mapping stays inside the system that already
holds the filenames, rather than being published into the log by every worker.

A CLAIM LINE ALONE IS NOT ENOUGH, which is the trap this module is shaped to avoid. One
discovery job walks a whole estate, so "job X was claimed" narrows a crash to a job that may
have touched thousands of documents. Correlation has to be per-document: `stage()` brackets each
native call with an enter and an exit, so the document with an enter and no exit at the moment
the log stops is the candidate. With a 12-slot pool there will be up to twelve such candidates,
which is a shortlist rather than the empty set the incident actually produced.
"""
from __future__ import annotations

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


def doc_id(identifier: str | None) -> str | None:
    """Opaque, stable, non-reversible handle for one document.

    Deterministic so the same document reads as the same `doc` across attempts, replicas and
    restarts — that is what makes "this document was open on all three crashes" a statement the
    log can support. Truncated to 12 hex (48 bits): collision-safe at estate scale, and short
    enough to eyeball across a page of log lines.
    """
    if identifier is None:
        return None
    return hashlib.sha256(str(identifier).encode("utf-8", "replace")).hexdigest()[:12]


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


@contextmanager
def stage(name: str, *, job_id: str | None = None, doc: str | None = None, **fields):
    """Bracket one processing step — above all a native one — with an enter and an exit.

    The enter is flushed BEFORE the call it guards, which is the whole contract: a step that
    segfaults leaves an enter with no exit, and that asymmetry is the finding. The exit carries
    the elapsed seconds, so a step that is merely slow is distinguishable from one that died.

    Re-raises everything. This observes; it must not change which exceptions the worker's own
    retry policy sees.
    """
    emit("stage.enter", stage=name, job_id=job_id, doc=doc, **fields)
    t0 = time.monotonic()
    try:
        yield
    except BaseException as exc:                       # noqa: BLE001 — observed, then re-raised
        emit("stage.error", stage=name, job_id=job_id, doc=doc,
             elapsed_s=round(time.monotonic() - t0, 3),
             error_type=type(exc).__name__, **fields)
        raise
    else:
        emit("stage.exit", stage=name, job_id=job_id, doc=doc,
             elapsed_s=round(time.monotonic() - t0, 3), **fields)
