"""No job handler may fail without saying so.

WHAT THIS IS FOR, and why it is not hypothetical. `api/handlers.py` carried 40 exception
handlers whose entire body was `pass` — 40 places where a failure produced no log, no metric
and no row. That is the same construct that hid a real bug for five PRs: `store.touch_job`
gained required arguments in #1075, a test double kept the old signature, and the worker wraps
its heartbeat in `try/except: pass` (api/worker.py:347), so a TypeError was raised and swallowed
on every single heartbeat while the suite stayed green. See
tests/test_store_doubles_match_the_real_store.py for that history.

The highest-stakes one was `_enqueue_proposals`: when `store.enqueue_proposals` failed, EVERY
remediation proposal for that (file, criterion) was lost and the reviewer saw a document with no
suggested fixes and no reason. That site is exercised end-to-end below, not merely counted.

WHAT IS AND IS NOT GUARDED. This pins `api/handlers.py` at zero. The rest of `api/` still holds
129 silent handlers across 31 files (`api/scanner.py` and `api/core.py` lead with 16 each, and
the worker heartbeat above is among them) — deliberately left alone rather than swept up in the
same pass, so this diff stays reviewable. That number is recorded here as a fact, not asserted:
a repo-wide ratchet would fail other sessions' unrelated work, and this file has no standing to
do that.
"""
from __future__ import annotations

import ast
import logging
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))

HANDLERS = ROOT / "api" / "handlers.py"
TREE = ast.parse(HANDLERS.read_text(), filename=str(HANDLERS))


def _is_silent(h: ast.ExceptHandler) -> bool:
    """A handler that discards its exception and produces no observable effect.

    `...` counts as well as `pass`. They are the same statement to the interpreter, and a guard
    that only knew the word `pass` could be satisfied by typing three dots."""
    if len(h.body) != 1:
        return False
    only = h.body[0]
    if isinstance(only, ast.Pass):
        return True
    return (isinstance(only, ast.Expr) and isinstance(only.value, ast.Constant)
            and only.value.value is Ellipsis)


ALL_HANDLERS = [h for n in ast.walk(TREE) if isinstance(n, ast.Try) for h in n.handlers]
SILENT = [h for h in ALL_HANDLERS if _is_silent(h)]
REPORTED = [h for h in ALL_HANDLERS
            if any(isinstance(c, ast.Name) and c.id == "_swallowed"
                   for node in h.body for c in ast.walk(node) if isinstance(c, ast.Name))]


def test_there_are_handlers_to_inspect():
    """Without this, a change that breaks the walk — a renamed file, a parse that yields nothing —
    turns every assertion below into a loop over an empty list, which reports as a pass. A floor,
    not a fixture: it is here to catch zero, not to be updated whenever a handler is added."""
    assert len(ALL_HANDLERS) >= 60, (
        f"only {len(ALL_HANDLERS)} except-handlers found in {HANDLERS.name} — the AST walk this "
        "guard depends on has probably stopped seeing the file, and is now checking nothing")


def test_no_exception_handler_discards_its_failure_silently():
    lines = sorted(h.lineno for h in SILENT)
    assert not lines, (
        f"{len(lines)} exception handler(s) in api/handlers.py have a body of just `pass` (or "
        f"`...`), at line(s) {lines}.\n\n"
        "A failure there produces no log, no metric and no row — nobody can find out it happened. "
        "Call `_swallowed(\"<function>: <what was being attempted> failed\", scan_id)` from the "
        "handler instead; it is rate-limited per (scan_id, operation) so a systematic failure "
        "escalates visibly without flooding a 6,000-file scan, and `exc_info` carries the "
        "traceback that identifies a signature drift as a drift.\n\n"
        "If a handler genuinely must stay silent, say so here and explain why — the point is that "
        "the decision is written down, not that the number never moves.")


def test_the_reporting_helper_is_actually_wired_in():
    """The assertion above is satisfied by ANY non-empty body, `return` included — which would be
    a control-flow change wearing the costume of an observability fix. This pins the mechanism."""
    assert len(REPORTED) >= 40, (
        f"only {len(REPORTED)} handler(s) in api/handlers.py report through _swallowed; 40 were "
        "converted. Handlers were made non-silent by some other means — check they did not start "
        "swallowing by `return` instead.")


# ── the helper's own behaviour ───────────────────────────────────────────────

@pytest.fixture
def swallowed():
    """handlers._swallowed with its rate-limit counter reset, so tests do not leak into each
    other through module state."""
    import handlers
    handlers._SWALLOWED_COUNTS.clear()
    yield handlers
    handlers._SWALLOWED_COUNTS.clear()


def test_a_swallowed_failure_is_logged_with_its_traceback(swallowed, caplog):
    with caplog.at_level(logging.WARNING, logger="handlers"):
        try:
            raise TypeError("enqueue_proposals() got an unexpected keyword argument 'finding_count'")
        except Exception:
            swallowed._swallowed("_enqueue_proposals: store.enqueue_proposals failed", "scan-1")
    assert len(caplog.records) == 1
    rec = caplog.records[0]
    assert "store.enqueue_proposals failed" in rec.getMessage()
    assert "scan-1" in rec.getMessage()
    # The traceback is the half that identifies a signature drift AS a drift, rather than as
    # some unspecified failure — it is what the swallowed heartbeat needed and did not have.
    assert rec.exc_info is not None
    assert "finding_count" in logging.Formatter().format(rec)


def test_a_systematic_failure_escalates_without_flooding(swallowed, caplog):
    """One line per document over a 6,000-file estate would bury the signal it exists to give.
    Powers of two keep the first failure loud and a persistent one visible, at ~13 lines per
    6,000 rather than 6,000."""
    with caplog.at_level(logging.WARNING, logger="handlers"):
        for _ in range(6000):
            try:
                raise RuntimeError("store is down")
            except Exception:
                swallowed._swallowed("_propose_text_findings: enqueueing 1.1.1 failed", "scan-2")
    assert len(caplog.records) == 13                      # 1,2,4,...,4096
    assert "occurrence" not in caplog.records[0].getMessage()   # the first is not annotated
    assert "occurrence 4096" in caplog.records[-1].getMessage()


def test_two_scans_do_not_share_a_rate_limit(swallowed, caplog):
    """Keyed per (scan_id, operation): a scan that has been failing all morning must not silence
    the first failure of the scan that starts next."""
    with caplog.at_level(logging.WARNING, logger="handlers"):
        for _ in range(50):
            try:
                raise RuntimeError("store is down")
            except Exception:
                swallowed._swallowed("op", "noisy-scan")
        before = len(caplog.records)
        try:
            raise RuntimeError("store is down")
        except Exception:
            swallowed._swallowed("op", "fresh-scan")
    assert len(caplog.records) == before + 1
    assert "fresh-scan" in caplog.records[-1].getMessage()


def test_the_helper_never_raises_out_of_a_handler_that_could_not(swallowed):
    """Every caller is a block that previously swallowed everything. If reporting could raise,
    this stopped being an observability change and became a control-flow one."""
    try:
        raise RuntimeError("boom")
    except Exception:
        swallowed._swallowed("op with no scan", None)     # scan_id is optional at some sites
        swallowed._swallowed("op with a %s in it", "scan-3")   # not a format string for the message


# ── the highest-stakes site, end to end ──────────────────────────────────────

def test_a_lost_batch_of_proposals_is_reported(monkeypatch, swallowed, caplog):
    """When store.enqueue_proposals fails, every proposal for that (file, criterion) is lost and
    the reviewer sees a document with no suggested fixes. It must not also be invisible.

    This is the site the signature-drift risk is live at: `_enqueue_proposals` does not pass
    `finding_count`, which the real Store.enqueue_proposals accepts — so a future caller that
    starts passing it fails exactly here, and used to do so in complete silence."""
    handlers = swallowed

    def _explode(*a, **kw):
        raise TypeError("enqueue_proposals() got an unexpected keyword argument 'finding_count'")

    monkeypatch.setattr(handlers, "_remediation_scope", lambda *a, **kw: None)
    monkeypatch.setattr(handlers.core.store, "enqueue_proposals", _explode, raising=False)

    with caplog.at_level(logging.WARNING, logger="handlers"):
        handlers._enqueue_proposals("scan-9", "report.docx", "1.1.1", "Non-text Content",
                                    [{"before": "", "proposed_value": "a chart of revenue"}])

    assert len(caplog.records) == 1, "the lost batch was swallowed without a word"
    msg = caplog.records[0].getMessage()
    assert "enqueue_proposals failed" in msg and "scan-9" in msg
    assert "finding_count" in logging.Formatter().format(caplog.records[0])
