"""No blanket exception handler in api/ may discard its failure without saying so.

WHAT THIS IS FOR, and why it is not hypothetical. `api/` carried 169 exception handlers whose
entire body was `pass` — 169 places where a failure produced no log, no metric and no row. That
is the construct that hid a real bug for five PRs: `store.touch_job` gained required arguments in
#1075, a test double kept the old signature, and the worker heartbeat wraps its call in exactly
this shape, so a TypeError was raised and swallowed on every single heartbeat while the suite
stayed green. See tests/test_store_doubles_match_the_real_store.py for that history. That
heartbeat is one of the handlers this now covers.

The highest-stakes one was `handlers._enqueue_proposals`: when `store.enqueue_proposals` failed,
EVERY remediation proposal for that (file, criterion) was lost and the reviewer saw a document
with no suggested fixes and no reason. That site is exercised end to end below, not merely
counted.

THE LINE THIS DRAWS, and why it is drawn there. A handler that NAMES its exception types has made
a bounded decision about an expected condition — a binary docx part that will not decode
(apply_link_text), an optional attribute that will not parse (geometry, office_structure), an
absent optional import (worker's google-auth probes), a stat that fails (scanner). Those stay
silent deliberately: logging them would be noise, and several run per row or per cell. It is the
BLANKET `except Exception:` — and the bare `except:` — that swallows everything including the
failures nobody predicted, and that is what this pins at zero.

That rule is not merely asserted against the repo as it stands; the classifier itself is tested
on synthetic snippets below, so a sweep that made it match nothing would fail rather than pass.
"""
from __future__ import annotations

import ast
import logging
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))

API = ROOT / "api"


def _is_blanket(h: ast.ExceptHandler) -> bool:
    """`except Exception:` or a bare `except:` — a handler that catches what it did not predict."""
    return h.type is None or ast.unparse(h.type) == "Exception"


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


def _reports(h: ast.ExceptHandler) -> bool:
    """This handler itself calls swallowed() — the mechanism, not merely a non-empty body.

    Direct statements only. Walking the whole subtree would count an outer handler whose body
    happens to contain a nested try/except that reports, which is a different handler."""
    return any(isinstance(st, ast.Expr) and isinstance(st.value, ast.Call)
               and isinstance(st.value.func, ast.Name) and st.value.func.id == "swallowed"
               for st in h.body)


def _scan(source: str) -> tuple[list, list, list]:
    """(all handlers, blanket-and-silent, narrow-and-silent) for one module's source."""
    tree = ast.parse(source)
    every = [h for n in ast.walk(tree) if isinstance(n, ast.Try) for h in n.handlers]
    silent = [h for h in every if _is_silent(h)]
    return every, [h for h in silent if _is_blanket(h)], [h for h in silent if not _is_blanket(h)]


def _api_modules():
    for p in sorted(API.rglob("*.py")):
        try:
            yield p, p.read_text()
        except UnicodeDecodeError:                       # pragma: no cover
            continue


EVERY, BLANKET_SILENT, NARROW_SILENT = [], [], []
REPORTED = []
for _p, _src in _api_modules():
    try:
        _every, _blanket, _narrow = _scan(_src)
    except SyntaxError:                                  # not this guard's job to report
        continue
    EVERY += [(_p, h) for h in _every]
    BLANKET_SILENT += [(_p, h) for h in _blanket]
    NARROW_SILENT += [(_p, h) for h in _narrow]
    REPORTED += [(_p, h) for h in _every if _reports(h)]


# ── the classifier itself, on synthetic code ────────────────────────────────

@pytest.mark.parametrize("src,blanket,narrow", [
    ("try:\n a()\nexcept Exception:\n pass\n", 1, 0),
    ("try:\n a()\nexcept:\n pass\n", 1, 0),
    ("try:\n a()\nexcept Exception:\n ...\n", 1, 0),
    ("try:\n a()\nexcept ValueError:\n pass\n", 0, 1),
    ("try:\n a()\nexcept (TypeError, ValueError):\n pass\n", 0, 1),
    ("try:\n a()\nexcept Exception:\n log()\n", 0, 0),
    ("def f():\n try:\n  a()\n except Exception:\n  return\n", 0, 0),
])
def test_the_classifier_tells_blanket_from_narrow(src, blanket, narrow):
    """The repo sweep below is only as good as this. A classifier that matched nothing — a
    renamed node, a changed unparse — would report the sweep as a pass."""
    _, b, n = _scan(src)
    assert (len(b), len(n)) == (blanket, narrow)


# ── the repo sweep ──────────────────────────────────────────────────────────

def test_there_are_handlers_to_inspect():
    """Without this, a change that breaks the walk — a moved package, a glob that matches nothing
    — turns every assertion below into a loop over an empty list, which reports as a pass. A
    floor, not a fixture: it is here to catch zero, not to be updated as handlers are added."""
    assert len(EVERY) >= 500, (
        f"only {len(EVERY)} except-handlers found under api/ — the AST walk this guard depends "
        "on has probably stopped seeing the tree, and is now checking nothing")


def test_no_blanket_handler_discards_its_failure_silently():
    where = sorted(f"{p.relative_to(ROOT)}:{h.lineno}" for p, h in BLANKET_SILENT)
    assert not where, (
        f"{len(where)} blanket exception handler(s) under api/ have a body of just `pass` (or "
        f"`...`):\n  " + "\n  ".join(where) + "\n\n"
        "A failure there produces no log, no metric and no row — nobody can find out it "
        "happened. Call `swallowed(\"<module>.<function>: <what was being attempted> failed\")` "
        "from the handler instead (api/swallowed.py); it is rate-limited per (scan_id, "
        "operation) so a systematic failure escalates visibly without flooding a 6,000-file "
        "scan, and exc_info carries the traceback that identifies a signature drift as a "
        "drift.\n\n"
        "If the handler is catching one specific, expected condition, catch THAT type rather "
        "than Exception — a narrow handler may stay silent, and saying which exception you mean "
        "is better documentation than a comment.")


def test_the_reporting_helper_is_actually_wired_in():
    """The assertion above is satisfied by ANY non-empty body, `return` included — which would be
    a control-flow change wearing the costume of an observability fix. This pins the mechanism."""
    assert len(REPORTED) >= 155, (
        f"only {len(REPORTED)} handler(s) under api/ report through swallowed(); 160 were "
        "converted. Handlers were made non-silent by some other means — check they did not start "
        "swallowing by `return` instead.")


def test_narrow_handlers_are_still_allowed_to_be_silent():
    """The exemption is real and in use, not a clause nobody exercises. If this ever reaches zero
    the rule above has quietly become 'no silent handler at all', which is not what was agreed."""
    assert len(NARROW_SILENT) >= 5, (
        "no narrow silent handlers found — either they were all converted (in which case the "
        "exemption in this file's docstring is now wrong) or the classifier has stopped "
        "recognising them")


# ── the helper's own behaviour ──────────────────────────────────────────────

@pytest.fixture
def sw():
    """api.swallowed with its rate-limit counter reset, so tests do not leak into each other."""
    import swallowed as mod
    mod.reset()
    yield mod
    mod.reset()


def test_a_swallowed_failure_is_logged_with_its_traceback(sw, caplog):
    with caplog.at_level(logging.WARNING, logger="swallowed"):
        try:
            raise TypeError("enqueue_proposals() got an unexpected keyword argument 'finding_count'")
        except Exception:
            sw.swallowed("_enqueue_proposals: store.enqueue_proposals failed", "scan-1")
    assert len(caplog.records) == 1
    rec = caplog.records[0]
    assert "store.enqueue_proposals failed" in rec.getMessage()
    assert "scan-1" in rec.getMessage()
    # The traceback is the half that identifies a signature drift AS a drift, rather than as some
    # unspecified failure — it is what the swallowed heartbeat needed and did not have.
    assert rec.exc_info is not None
    assert "finding_count" in logging.Formatter().format(rec)


def test_a_systematic_failure_escalates_without_flooding(sw, caplog):
    """One line per document over a 6,000-file estate would bury the signal it exists to give.
    Powers of two keep the first failure loud and a persistent one visible, at ~13 lines per
    6,000 rather than 6,000."""
    with caplog.at_level(logging.WARNING, logger="swallowed"):
        for _ in range(6000):
            try:
                raise RuntimeError("store is down")
            except Exception:
                sw.swallowed("_propose_text_findings: enqueueing 1.1.1 failed", "scan-2")
    assert len(caplog.records) == 13                           # 1, 2, 4, ... 4096
    assert "occurrence" not in caplog.records[0].getMessage()   # the first is not annotated
    assert "occurrence 4096" in caplog.records[-1].getMessage()


def test_two_scans_do_not_share_a_rate_limit(sw, caplog):
    """Keyed per (scan_id, operation): a scan that has been failing all morning must not silence
    the first failure of the scan that starts next."""
    with caplog.at_level(logging.WARNING, logger="swallowed"):
        for _ in range(50):
            try:
                raise RuntimeError("store is down")
            except Exception:
                sw.swallowed("op", "noisy-scan")
        before = len(caplog.records)
        try:
            raise RuntimeError("store is down")
        except Exception:
            sw.swallowed("op", "fresh-scan")
    assert len(caplog.records) == before + 1
    assert "fresh-scan" in caplog.records[-1].getMessage()


def test_the_helper_never_raises_out_of_a_handler_that_could_not(sw):
    """Every caller is a block that previously swallowed everything. If reporting could raise,
    this stopped being an observability change and became a control-flow one."""
    try:
        raise RuntimeError("boom")
    except Exception:
        sw.swallowed("op with no scan")                    # scan_id is omitted at most sites
        sw.swallowed("op with a %s in it", "scan-3")       # the message is not a format string


# ── two sites, end to end ───────────────────────────────────────────────────

def test_a_lost_batch_of_proposals_is_reported(monkeypatch, sw, caplog):
    """When store.enqueue_proposals fails, every proposal for that (file, criterion) is lost and
    the reviewer sees a document with no suggested fixes. It must not also be invisible.

    This is the site the signature-drift risk is live at: `_enqueue_proposals` does not pass
    `finding_count`, which the real Store.enqueue_proposals accepts — so a future caller that
    starts passing it fails exactly here, and used to do so in complete silence."""
    import handlers

    def _explode(*a, **kw):
        raise TypeError("enqueue_proposals() got an unexpected keyword argument 'finding_count'")

    monkeypatch.setattr(handlers, "_remediation_scope", lambda *a, **kw: None)
    monkeypatch.setattr(handlers.core.store, "enqueue_proposals", _explode, raising=False)

    with caplog.at_level(logging.WARNING, logger="swallowed"):
        handlers._enqueue_proposals("scan-9", "report.docx", "1.1.1", "Non-text Content",
                                    [{"before": "", "proposed_value": "a chart of revenue"}])

    assert len(caplog.records) == 1, "the lost batch was swallowed without a word"
    msg = caplog.records[0].getMessage()
    assert "enqueue_proposals failed" in msg and "scan-9" in msg
    assert "finding_count" in logging.Formatter().format(caplog.records[0])


def test_a_broken_worker_log_is_reported(monkeypatch, sw, caplog):
    """worker._log is the outer of two guards over the job-log path, and its whole point is that
    a logging fault cannot change a job's outcome. That stays true — it still swallows — but the
    fault is now visible instead of perfectly silent, which is the shape the #1075 heartbeat
    drift needed and did not have."""
    import worker

    def _explode(*a, **kw):
        raise RuntimeError("stdout is gone")

    monkeypatch.setattr(worker.joblog, "emit", _explode)
    with caplog.at_level(logging.WARNING, logger="swallowed"):
        worker._log("job.claimed", job_id="j-1")            # must not raise
    assert len(caplog.records) == 1
    assert "worker._log" in caplog.records[0].getMessage()
