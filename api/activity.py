"""The one line that says what ACP is doing right now — which file, which criterion, what action.

WHY THIS EXISTS. Both long-running paths already report progress and neither reports anything a
person can read. The scan sends `{phase, files_found, files_done, current}` — a filename and a
count — and remediation sends `{in_flight, failed, latest_file}`, which is a queue depth. So a
25-page document sits for forty seconds under "analysing" with no indication of whether it is
OCRing images, waiting on a vision model, or stuck, and the honest answer to "what is it doing?"
is that nobody can tell. That is a bad experience on a demo and a worse one on a hospital's
estate, where the user is being asked to trust a tool with patient documents.

ONE CHANNEL, BOTH PATHS. Assessment and remediation are different jobs in different processes
(the scan runs under a job id, remediation fans out per file), so they cannot share a job record.
They CAN share a scan id, which is what this keys on. `core`'s existing job store already gives a
Redis-or-memory backing with a TTL and multi-replica reads, so this reuses it under a synthetic
`activity:<scan_id>` key rather than adding a table or a migration for a value whose whole point
is that it is transient.

BEST-EFFORT, ALWAYS. Nothing here may raise into the pipeline. A progress line that can fail a
scan is a downgrade over having no progress line, so every write is wrapped and every read
returns None rather than propagating. This is deliberately the only module in the remediation
path allowed to swallow errors silently.

THE STRING IS BUILT HERE, NOT AT THE CALL SITE. Callers pass structured parts (file, sc, action,
detail) and this renders them, so the phrasing stays consistent across a dozen call sites and a
UI can render the parts itself instead of parsing prose back out of a sentence.
"""
from __future__ import annotations

import threading
import time
from swallowed import swallowed

# Criterion names for the human-readable line. Kept here rather than imported from
# assessment_policy because that module builds a much larger structure and this needs four words
# per criterion; a lookup miss falls back to the bare number, which is still readable.
_SC_NAMES = {
    "1.1.1": "Non-text Content", "1.3.1": "Info and Relationships",
    "1.3.2": "Meaningful Sequence", "1.3.3": "Sensory Characteristics",
    "1.4.1": "Use of Color", "1.4.3": "Contrast (Minimum)", "1.4.5": "Images of Text",
    "1.4.11": "Non-text Contrast", "2.1.2": "No Keyboard Trap", "2.4.2": "Page Titled",
    "2.4.4": "Link Purpose (In Context)", "2.4.6": "Headings and Labels",
    "3.1.1": "Language of Page", "3.1.2": "Language of Parts", "3.3.2": "Labels or Instructions",
    "4.1.2": "Name, Role, Value",
}


def sc_name(sc: str) -> str:
    return _SC_NAMES.get((sc or "").strip(), sc or "")


def line(*, file: str | None = None, sc: str | None = None, action: str = "",
         detail: str | None = None) -> str:
    """Render the parts into one sentence.

    Ordered file → criterion → action → detail because that is the order a reader scans for
    "is it on MY document yet?", which is the question the line exists to answer.
    """
    bits = []
    if file:
        bits.append(file)
    if sc:
        name = sc_name(sc)
        bits.append(f"{sc} {name}" if name and name != sc else sc)
    if action:
        bits.append(action)
    out = " · ".join(bits)
    if detail:
        out = f"{out} — {detail}" if out else detail
    return out


# Minimum seconds between published lines for one scan. Per-FINDING publishing is what makes
# the line useful — "image 12 of 35" is the answer to "is it stuck?" that a stage name cannot
# give — but a finding is not always slow. A vision call takes seconds and a table-header fix
# takes microseconds, so the same loop that publishes 35 useful lines over two minutes can
# publish 400 useless ones over 40ms, each a Redis round-trip on the remediation hot path.
#
# 0.2s caps it at five writes a second. Nothing is lost that anyone could have read: the UI polls
# on the order of a second, so lines dropped here were never going to reach a screen. Stage
# boundaries pass force=True and are never dropped, because those are the transitions a user
# reads as "it moved on" and skipping one leaves the line stale on the wrong criterion.
_MIN_INTERVAL = 0.2
_last: dict[str, float] = {}


def record(scan_id: str | None, *, file: str | None = None, sc: str | None = None,
           action: str = "", detail: str | None = None, phase: str | None = None,
           force: bool = False) -> None:
    """Publish the current activity for a scan. Never raises.

    A no-op without a scan_id, which is the case for every offline caller — the benchmark
    harnesses, the CLI, and the tests all drive remediation with `scan_id=None`, and none of
    them should pay for a store round-trip or fail because a store is absent.

    `force` bypasses the rate limit. Use it for stage transitions, never for per-item updates.
    """
    if not scan_id:
        return
    now = time.time()
    if not force and now - _last.get(scan_id, 0.0) < _MIN_INTERVAL:
        return
    _last[scan_id] = now
    try:
        import core
        core.set_job(f"activity:{scan_id}", {
            "text": line(file=file, sc=sc, action=action, detail=detail),
            "file": file, "sc": sc, "sc_name": sc_name(sc) if sc else None,
            "action": action, "detail": detail, "phase": phase, "at": now,
        })
    except Exception:
        # a progress line must never be able to fail the work it describes
        swallowed("activity.record: publishing the activity line to the job state failed", scan_id)


def current(scan_id: str) -> dict | None:
    """The last published activity for a scan, or None. Never raises."""
    try:
        import core
        return core.get_job_state(f"activity:{scan_id}")
    except Exception:
        return None


# ── concurrent assessment ─────────────────────────────────────────────────────
#
# Remediation works one document at a time, so `record` can publish a single line and be
# truthful. ASSESSMENT fans out over a thread pool (scanner._SCAN_WORKERS, up to 8), and a single
# last-writer-wins line under that flips between eight documents several times a second — which
# reads as thrashing and tells the user less than the file count already did.
#
# So the in-flight set is tracked and the headline is rendered FROM it. The oldest entry is shown,
# not the newest: the question a progress line answers is "is it stuck?", and the document that
# has been running longest is the one that answers it. The newest is the least interesting thing
# on screen — it is by definition the one that just started.
#
# THE MAP IS IN-PROCESS, NOT IN THE STORE, and that is the whole reason this is correct under
# concurrency. Eight threads doing read-modify-write on one Redis key race, and a lost REMOVAL
# leaves a finished document in the headline forever. These workers are threads in one process,
# so a plain dict under a lock is both cheaper and race-free; only the rendered result is
# published. `_STALE` prunes anything a crashed or abandoned worker left behind, so the map is
# self-healing even if `finish_file` is never reached.
_STALE = 300.0
_inflight: dict[str, dict[str, dict]] = {}
_inflight_lock = threading.Lock()


def _render_inflight(scan_id: str, now: float) -> dict | None:
    """Headline for the current in-flight set. Caller holds the lock."""
    files = _inflight.get(scan_id) or {}
    for f in [f for f, v in files.items() if now - v["at"] > _STALE]:
        files.pop(f, None)
    if not files:
        return None
    oldest_file = min(files, key=lambda f: files[f]["at"])
    v = files[oldest_file]
    text = line(file=oldest_file, sc=v.get("sc"), action=v.get("action"),
                detail=v.get("detail"))
    if len(files) > 1:
        # Named, not merely counted: "+2 more" tells the user the tool is busy, the count alone
        # would let them think their own document had been skipped.
        text = f"{text}  (+{len(files) - 1} more in progress)"
    return {"text": text, "file": oldest_file, "sc": v.get("sc"),
            "sc_name": sc_name(v["sc"]) if v.get("sc") else None,
            "action": v.get("action"), "detail": v.get("detail"),
            "phase": v.get("phase"), "in_flight": len(files), "at": now}


def _publish(scan_id: str, payload: dict | None, *, force: bool) -> None:
    now = payload["at"] if payload else time.time()
    if not force and now - _last.get(scan_id, 0.0) < _MIN_INTERVAL:
        return
    _last[scan_id] = now
    try:
        import core
        core.set_job(f"activity:{scan_id}", payload or {"text": None, "in_flight": 0, "at": now})
    except Exception:
        swallowed("activity._publish: publishing in-flight file state to the job state failed", scan_id)


def record_file(scan_id: str | None, file: str, *, sc: str | None = None, action: str = "",
                detail: str | None = None, phase: str | None = None,
                force: bool = False) -> None:
    """One document's current rule, within a concurrent assessment. Never raises."""
    if not scan_id or not file:
        return
    now = time.time()
    try:
        with _inflight_lock:
            _inflight.setdefault(scan_id, {})[file] = {
                "sc": sc, "action": action, "detail": detail, "phase": phase, "at":
                    _inflight.get(scan_id, {}).get(file, {}).get("at", now)}
            payload = _render_inflight(scan_id, now)
        _publish(scan_id, payload, force=force)
    except Exception:
        swallowed("activity.record_file: recording an in-flight file failed", scan_id)


def finish_file(scan_id: str | None, file: str) -> None:
    """This document is done — drop it from the headline. Never raises.

    Forced, because a removal is exactly the update the rate limit must not swallow: dropping it
    leaves a finished document named on screen while something else is running, which is the one
    way this line can state something false rather than merely stale.
    """
    if not scan_id or not file:
        return
    try:
        with _inflight_lock:
            (_inflight.get(scan_id) or {}).pop(file, None)
            payload = _render_inflight(scan_id, time.time())
        _publish(scan_id, payload, force=True)
    except Exception:
        swallowed("activity.finish_file: clearing a finished in-flight file failed", scan_id)
