"""Denial telemetry (PRD §12's `role.access_denied`) — recorded, and deliberately not once per
request.

WHY THIS IS NOT `log_decision(...)` AT THE REFUSAL SITE. The obvious implementation writes an
audit row every time the capability gate refuses. That is correct exactly once and wrong under
the conditions denials actually occur in:

  * A DENIED CLIENT RETRIES. The SPA polls — scan status, job progress, the activity snapshot —
    and a user whose role was narrowed mid-session keeps those polls running until the navigation
    catches up. That is a denial every few seconds, per open tab, writing a row each time.
  * THE AUDIT LOG IS APPEND-ONLY. api/store.py's decision_log is never updated or deleted, by
    design — it is the record an auditor reads. Filling it with ten thousand copies of one fact
    does not just cost storage; it buries the role changes and publish approvals that are the
    reason the log exists.
  * IT IS A WRITE AMPLIFIER ON A REFUSED REQUEST. The cheapest possible response to "you may not
    do this" should not be a database INSERT. An unauthenticated flood already stops at the access
    gate, but an AUTHENTICATED user hammering an endpoint they lack would turn each 403 into a
    write — a denial-of-service with a valid session.

So denials are COALESCED: the first of a kind is recorded immediately, and repeats of the same
kind from the same person are suppressed for a window, then recorded once with a count of what
was suppressed. An operator asking "was Jane refused?" gets a yes; an operator asking "how often"
gets a number; the log does not grow without bound in either case.

WHAT "THE SAME KIND" MEANS: one person, one capability requirement. Not one person and one URL —
`/scans/a/status` and `/scans/b/status` are the same refusal to the operator reading it, and
keying on the path would defeat the coalescing entirely for any per-object route, which is most
of them.

IN-PROCESS, AND THEREFORE PER-REPLICA. The window lives in this module's memory, so N API
replicas record up to N first-denials for the same event. That is a deliberate trade against the
alternative — a shared counter in the database, which is another write on the path we are trying
to keep cheap. N rows instead of one is legible; ten thousand is not, and that is the failure
being fixed.
"""
from __future__ import annotations

import threading
import time

# How long repeats of one (person, requirement) stay suppressed. Two minutes is long enough to
# absorb a polling SPA — the busiest poll in this app is a few seconds — and short enough that a
# user who is genuinely blocked, goes away and comes back still produces a second entry rather
# than vanishing from the record.
WINDOW_SECONDS = 120.0

# A ceiling on distinct keys held in memory, so a hostile or merely broken client cannot grow this
# without bound by varying its identity. When it is hit the OLDEST entries go first: a key whose
# window has nearly elapsed is the one whose eviction costs least — it was about to be recorded
# again anyway.
MAX_TRACKED = 2048

_lock = threading.Lock()
# key -> [window_started_at, suppressed_since_then]
_seen: dict[tuple[str, tuple[str, ...]], list] = {}


def _key(email: str | None, required) -> tuple[str, tuple[str, ...]]:
    return ((email or "anonymous").strip().lower(), tuple(sorted(required or ())))


def should_record(email: str | None, required, *, now: float | None = None) -> tuple[bool, int]:
    """Should this denial be written, and how many were suppressed before it?

    Returns (record, suppressed_count). `record` is True for the first denial of a kind and again
    once the window elapses; `suppressed_count` is how many were swallowed in between, so the row
    that does get written can say so rather than understating the frequency.

    Both halves matter. Recording only the first would tell an operator that Jane was refused once
    when she was refused four hundred times, which is a different situation — the first reads as a
    misclick, the second as a role that is wrong.
    """
    now = time.time() if now is None else now
    k = _key(email, required)
    with _lock:
        entry = _seen.get(k)
        if entry is None or (now - entry[0]) >= WINDOW_SECONDS:
            suppressed = entry[1] if entry is not None else 0
            _seen[k] = [now, 0]
            _evict_if_needed(now)
            return True, suppressed
        entry[1] += 1
        return False, 0


def _evict_if_needed(now: float) -> None:
    """Caller holds the lock. Drops the oldest windows once the map is over its ceiling."""
    if len(_seen) <= MAX_TRACKED:
        return
    for k, _ in sorted(_seen.items(), key=lambda kv: kv[1][0])[:len(_seen) - MAX_TRACKED]:
        _seen.pop(k, None)


def detail(email: str | None, required, *, role: str | None, method: str, path: str,
           suppressed: int) -> str:
    """The audit row's text.

    NAMES THE ROUTE PATTERN, NOT THE URL. `/scans/{sid}/status` rather than
    `/scans/9f2c.../status`: the concrete id is the customer's data, the pattern is the
    permission, and it is the permission an auditor is reading this row about. It also keeps rows
    for one refusal identical, which is what makes them countable.
    """
    who = (email or "anonymous").strip().lower()
    as_role = f" as {role}" if role else " with no workspace role"
    also = f" (+{suppressed} more in the last {int(WINDOW_SECONDS)}s)" if suppressed else ""
    return (f"{who}{as_role} was refused {method} {path} — needs "
            f"{' or '.join(sorted(required or ())) or 'an unknown capability'}{also}")


def reset() -> None:
    """Test seam. The window is process-global, so a test that does not clear it is one whose
    result depends on what ran before it."""
    with _lock:
        _seen.clear()
