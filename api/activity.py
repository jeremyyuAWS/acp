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

import time

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


def record(scan_id: str | None, *, file: str | None = None, sc: str | None = None,
           action: str = "", detail: str | None = None, phase: str | None = None) -> None:
    """Publish the current activity for a scan. Never raises.

    A no-op without a scan_id, which is the case for every offline caller — the benchmark
    harnesses, the CLI, and the tests all drive remediation with `scan_id=None`, and none of
    them should pay for a store round-trip or fail because a store is absent.
    """
    if not scan_id:
        return
    try:
        import core
        core.set_job(f"activity:{scan_id}", {
            "text": line(file=file, sc=sc, action=action, detail=detail),
            "file": file, "sc": sc, "sc_name": sc_name(sc) if sc else None,
            "action": action, "detail": detail, "phase": phase, "at": time.time(),
        })
    except Exception:
        pass          # a progress line must never be able to fail the work it describes


def current(scan_id: str) -> dict | None:
    """The last published activity for a scan, or None. Never raises."""
    try:
        import core
        return core.get_job_state(f"activity:{scan_id}")
    except Exception:
        return None
