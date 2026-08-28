"""Regression tests for the two bugs that caused "this scan never started".

Bug 1 (early init_scan_run):
  _scan_discover called init_scan_run AFTER _list(), which can take minutes on a
  large estate. The frontend polls GET /scans/{id} once per second and gives up at
  45 misses (NEVER_STARTED_AFTER_MISSES=45), so a slow listing falsely looked like
  a dead replica. Fix: init_scan_run is called BEFORE _list(), with total=0; the
  count and scope are written via set_scan_files / merge_scan_scope afterward.

Bug 2 (token not in job payload):
  Tokens were stored in the API replica's in-memory dict (core.SCAN_TOKENS) and
  looked up by _scan_discover via core.get_scan_tokens(). In split topology the
  worker container has a separate process — it can never reach the API's in-memory
  state — so the token lookup always returned {} and Drive/SP scans silently ran
  without credentials (or crashed). Fix: enqueue_job carries drive_token/sp_token
  in the payload; _scan_discover prefers the payload value over the in-memory store.
"""
from __future__ import annotations
import sys
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))

# handlers.py has a module-level `from remediate import remediate_html`, which chains
# into lxml (not installed in the test environment). Stub the entire dependency tree
# once so every test in this file can `import handlers` without error.
#
# reportlab is NOT part of that chain — handlers.py's own imports (core, provenance, worker,
# scanner, remediate) never touch it — and it IS genuinely installed in this environment, so
# stubbing it here is both unnecessary and actively harmful: `sys.modules.setdefault` only
# takes effect while the real "reportlab.graphics.charts" hasn't been imported yet, which at
# pytest COLLECTION time (when this loop runs) is true regardless of whether some OTHER test
# file will need the real package later — most consumers only reach it lazily, via `from app
# import app` inside a fixture body, not at their own module level. Found live 2026-08-28: this
# stub then permanently replaces "reportlab.graphics.charts" in sys.modules with a MagicMock
# lacking __path__, and since nothing ever reverts a bare sys.modules.setdefault, every later
# test whose fixture pulls in api/report.py's `from reportlab.graphics.charts.piecharts import
# Pie` fails with "reportlab.graphics.charts is not a package" — a wide, seemingly unrelated
# spread of failures across whatever test files happen to run after this one in the same
# process, entirely dependent on file-execution order.
for _mod in ("lxml", "lxml.html"):
    sys.modules.setdefault(_mod, MagicMock())

_remediate_stub = MagicMock()
_remediate_stub.remediate_html = MagicMock(return_value=b"<html/>")
sys.modules.setdefault("remediate", _remediate_stub)


@pytest.fixture(autouse=True)
def _no_first_scan_retry(isolated_store, monkeypatch):
    """Keep the first-scan retry out of a file that is not about the first-scan retry.

    `_scan_discover` retries a listing once, after `time.sleep(5)`, when it returns 0 files for
    a source that has never been scanned. Every store here is fresh, so every empty listing in
    this file qualifies — and none of these tests is about that behaviour: they are about
    init_scan_run ordering and token forwarding.

    Left alone it costs more than time. `test_scan_row_exists_before_list_returns` runs
    `_scan_discover` on a thread and joins with a 3s timeout, so a 5s sleep means the join gives
    up while the thread is still inside `patch.dict(sys.modules, {"scanner": ...})` — a
    PROCESS-GLOBAL patch. `sys.modules["scanner"]` then stays a MagicMock for whatever runs next,
    and the damage lands somewhere else entirely: 13 tests in test_sweep_failure_visible.py and
    test_smb_source.py failed with `assert <MagicMock name='mock._flag_on()'> is False`, having
    imported a scanner that another file had replaced and not put back.

    The threaded tests below now hold that patch on the main thread instead, so the leak cannot
    recur even if something in here gets slow again. This fixture removes the sleep that made it
    happen, and ~25s of dead wall-clock across the file with it.

    `last_nonempty_run_for_source` is also patched: with the fix that replaced `_first_scan` with
    `not _baseline_id`, any scan returning 0 files where no non-empty baseline exists would retry.
    Since `isolated_store` is a fresh empty store, `last_nonempty_run_for_source` returns None by
    default — which would trigger the retry and its 5s sleep in every test here. The tests in this
    file are not about that behaviour, so both lookups are suppressed together.
    """
    monkeypatch.setattr(isolated_store, "previous_run_for_source",
                        lambda *a, **kw: "prior-scan-exists", raising=False)
    monkeypatch.setattr(isolated_store, "last_nonempty_run_for_source",
                        lambda *a, **kw: "prior-nonempty-scan-exists", raising=False)


# ── helpers ──────────────────────────────────────────────────────────────────

def _wait_until(predicate, timeout=3.0, interval=0.02):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def _fake_rubric():
    rb = MagicMock()
    rb.name = "test-rubric"
    rb.hash = "abc123"
    return rb


def _call_discover(payload, isolated_store, monkeypatch, *,
                   list_fn=None, get_scan_tokens_ret=None):
    """Call _scan_discover with enough stubs for it to run.

    list_fn: replacement for scanner._list — defaults to returning [].
    get_scan_tokens_ret: what core.get_scan_tokens returns; defaults to {}.
    """
    import core
    import handlers

    monkeypatch.setattr(core, "store", isolated_store)
    if get_scan_tokens_ret is not None:
        monkeypatch.setattr(core, "get_scan_tokens", lambda sid: get_scan_tokens_ret)

    fake_list = list_fn or (lambda *a, **kw: [])

    # Heavy scanner symbols used inside _scan_discover
    fake_scanner = MagicMock()
    fake_scanner._list = fake_list
    fake_scanner._drive_service = lambda tok: MagicMock()
    fake_scanner.ACP = ROOT
    fake_scanner.FANOUT_MAX_FILES = 5000
    fake_scanner._scope_for_listing = lambda user: {}

    fake_rubric_mod = MagicMock()
    fake_rubric_mod.Rubric.load_active.return_value = _fake_rubric()

    monkeypatch.setattr(handlers, "_defer_analysis_to_assess", lambda: True)
    monkeypatch.setattr(handlers, "_enqueue_analysis", lambda *a, **kw: None)

    with patch.dict(sys.modules, {"scanner": fake_scanner, "rubric": fake_rubric_mod}):
        handlers._scan_discover(payload, {"scan_id": payload.get("scan_id")})


# ── Bug 1: init_scan_run is called BEFORE _list() ────────────────────────────

def test_scan_row_exists_before_list_returns(isolated_store, monkeypatch):
    """The scan_runs row must appear while _list() is still running.

    This is the live-incident regression: if init_scan_run were still called after
    _list() a 60-second listing on a large estate would consume all 45 poll misses
    and the frontend would throw "this scan never started" for a scan that was alive."""
    import core
    import handlers

    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setattr(core, "get_scan_tokens", lambda sid: {})
    monkeypatch.setattr(handlers, "_defer_analysis_to_assess", lambda: True)
    monkeypatch.setattr(handlers, "_enqueue_analysis", lambda *a, **kw: None)

    listing_started = threading.Event()
    listing_may_finish = threading.Event()
    row_existed_before_list_returned = threading.Event()

    def slow_list(*args, **kwargs):
        listing_started.set()
        listing_may_finish.wait(timeout=3)
        return []

    fake_scanner = MagicMock()
    fake_scanner._list = slow_list
    fake_scanner._drive_service = lambda tok: MagicMock()
    fake_scanner.ACP = ROOT
    fake_scanner.FANOUT_MAX_FILES = 5000
    fake_scanner._scope_for_listing = lambda user: {}

    fake_rubric_mod = MagicMock()
    fake_rubric_mod.Rubric.load_active.return_value = _fake_rubric()

    payload = {"scan_id": "s_bug1", "source": "local", "user": "test@x.com"}

    # patch.dict on the MAIN thread, spanning start→join, not inside the worker. sys.modules is
    # process-global: with the patch held by a daemon thread, a join that times out leaves
    # "scanner" mocked for every test that runs next, and the failure surfaces in an unrelated
    # file (see _no_first_scan_retry). Held here, the context manager exits on the way out of
    # this test whatever the thread is doing.
    with patch.dict(sys.modules, {"scanner": fake_scanner, "rubric": fake_rubric_mod}):
        t = threading.Thread(target=handlers._scan_discover,
                             args=(payload, {"scan_id": "s_bug1"}), daemon=True)
        t.start()

        assert _wait_until(listing_started.is_set, timeout=3), "_list never started"

        # While _list is still running, the scan_runs row must already exist.
        row = isolated_store.get_scan(payload["scan_id"])
        assert row is not None, (
            "scan_runs row not found while _list() was still running — "
            "a slow listing makes GET /scans/{id} return 404 and the frontend "
            "throws 'this scan never started'"
        )
        run = row.get("run", row)  # get_scan returns {"run": {...}, "files": [...]}
        assert run.get("completed_at") is None

        listing_may_finish.set()
        t.join(timeout=5)
        # Fail here rather than let a still-running thread reach into the next test.
        assert not t.is_alive(), "_scan_discover thread did not finish — it would outlive the patch"


def test_scan_row_has_zero_files_before_list_returns(isolated_store, monkeypatch):
    """init_scan_run is called with total=0; set_scan_files updates the count later."""
    import core
    import handlers

    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setattr(core, "get_scan_tokens", lambda sid: {})
    monkeypatch.setattr(handlers, "_defer_analysis_to_assess", lambda: True)
    monkeypatch.setattr(handlers, "_enqueue_analysis", lambda *a, **kw: None)

    listing_started = threading.Event()
    listing_may_finish = threading.Event()

    def slow_list(*args, **kwargs):
        listing_started.set()
        listing_may_finish.wait(timeout=3)
        return [{"file": "a.docx", "name": "a.docx"}, {"file": "b.docx", "name": "b.docx"}]

    fake_scanner = MagicMock()
    fake_scanner._list = slow_list
    fake_scanner._drive_service = lambda tok: MagicMock()
    fake_scanner.ACP = ROOT
    fake_scanner.FANOUT_MAX_FILES = 5000
    fake_scanner._scope_for_listing = lambda user: {}

    fake_rubric_mod = MagicMock()
    fake_rubric_mod.Rubric.load_active.return_value = _fake_rubric()

    payload = {"scan_id": "s_bug1b", "source": "local", "user": "test@x.com"}

    # Main-thread patch spanning start→join, for the reason given in the test above.
    with patch.dict(sys.modules, {"scanner": fake_scanner, "rubric": fake_rubric_mod}):
        t = threading.Thread(target=handlers._scan_discover,
                             args=(payload, {"scan_id": "s_bug1b"}), daemon=True)
        t.start()
        assert _wait_until(listing_started.is_set, timeout=3)

        row = isolated_store.get_scan("s_bug1b")
        assert row is not None
        run = row.get("run", row)  # get_scan returns {"run": {...}, "files": [...]}
        # files=0 while listing is in progress
        assert run.get("files") == 0, f"expected files=0 before listing done, got {run.get('files')}"

        listing_may_finish.set()
        t.join(timeout=5)
        assert not t.is_alive(), "_scan_discover thread did not finish — it would outlive the patch"

    # After listing completes the count is updated to the real number.
    final = isolated_store.get_scan("s_bug1b")
    assert final is not None
    final_run = final.get("run", final)
    assert final_run.get("files") == 2, f"expected 2 files after listing, got {final_run.get('files')}"


# ── Bug 2: drive_token / sp_token from job payload ───────────────────────────

def test_drive_token_from_payload_reaches_drive_service(isolated_store, monkeypatch):
    """When get_scan_tokens returns {} (worker replica without Redis), the Drive
    token carried in the job payload must still reach _drive_service."""
    import core
    import handlers

    monkeypatch.setattr(core, "store", isolated_store)
    # Simulate empty in-memory token store — the worker container's reality.
    monkeypatch.setattr(core, "get_scan_tokens", lambda sid: {})
    monkeypatch.setattr(handlers, "_defer_analysis_to_assess", lambda: True)
    monkeypatch.setattr(handlers, "_enqueue_analysis", lambda *a, **kw: None)

    received_token = []

    def capturing_drive_service(tok):
        received_token.append(tok)
        return MagicMock()

    fake_scanner = MagicMock()
    fake_scanner._list = lambda *a, **kw: []
    fake_scanner._drive_service = capturing_drive_service
    fake_scanner.ACP = ROOT
    fake_scanner.FANOUT_MAX_FILES = 5000
    fake_scanner._scope_for_listing = lambda user: {}

    fake_rubric_mod = MagicMock()
    fake_rubric_mod.Rubric.load_active.return_value = _fake_rubric()

    payload = {
        "scan_id": "s_bug2_drive",
        "source": "drive",
        "user": "test@x.com",
        "drive_token": "PAYLOAD_DRIVE_TOKEN_XYZ",
    }

    with patch.dict(sys.modules, {"scanner": fake_scanner, "rubric": fake_rubric_mod}):
        handlers._scan_discover(payload, {"scan_id": "s_bug2_drive"})

    assert received_token == ["PAYLOAD_DRIVE_TOKEN_XYZ"], (
        f"_drive_service received {received_token!r} instead of the payload token — "
        "in split topology (worker separate from API replica) the in-memory token store "
        "is always empty and only the payload token can authenticate"
    )


def test_sp_token_from_payload_reaches_list(isolated_store, monkeypatch):
    """SharePoint token from the payload must be forwarded to _list as sp_token."""
    import core
    import handlers

    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setattr(core, "get_scan_tokens", lambda sid: {})
    monkeypatch.setattr(handlers, "_defer_analysis_to_assess", lambda: True)
    monkeypatch.setattr(handlers, "_enqueue_analysis", lambda *a, **kw: None)
    monkeypatch.setattr(isolated_store, "previous_run_for_source", lambda *a, **kw: "fake_prev_scan")
    monkeypatch.setattr(isolated_store, "last_nonempty_run_for_source",
                        lambda *a, **kw: "fake_nonempty_scan", raising=False)

    received_sp = []

    def capturing_list(*args, **kwargs):
        received_sp.append(kwargs.get("sp_token"))
        return []

    fake_scanner = MagicMock()
    fake_scanner._list = capturing_list
    fake_scanner._drive_service = lambda tok: MagicMock()
    fake_scanner.ACP = ROOT
    fake_scanner.FANOUT_MAX_FILES = 5000
    fake_scanner._scope_for_listing = lambda user: {}

    fake_rubric_mod = MagicMock()
    fake_rubric_mod.Rubric.load_active.return_value = _fake_rubric()

    payload = {
        "scan_id": "s_bug2_sp",
        "source": "sharepoint",
        "user": "test@x.com",
        "sp_token": "PAYLOAD_SP_TOKEN_ABC",
    }

    with patch.dict(sys.modules, {"scanner": fake_scanner, "rubric": fake_rubric_mod}):
        handlers._scan_discover(payload, {"scan_id": "s_bug2_sp"})

    assert received_sp == ["PAYLOAD_SP_TOKEN_ABC"], (
        f"_list received sp_token={received_sp!r} instead of the payload token"
    )


def test_payload_token_preferred_over_in_memory_store(isolated_store, monkeypatch):
    """When both payload and in-memory store have a token, the payload token wins.

    The in-memory token may belong to a different user if two scans race on the same
    API replica; the payload token is always stamped at enqueue time for THIS scan."""
    import core
    import handlers

    monkeypatch.setattr(core, "store", isolated_store)
    # In-memory store has a DIFFERENT (stale/wrong) token.
    monkeypatch.setattr(core, "get_scan_tokens",
                        lambda sid: {"drive": "IN_MEMORY_STALE_TOKEN"})
    monkeypatch.setattr(handlers, "_defer_analysis_to_assess", lambda: True)
    monkeypatch.setattr(handlers, "_enqueue_analysis", lambda *a, **kw: None)

    received_token = []

    def capturing_drive_service(tok):
        received_token.append(tok)
        return MagicMock()

    fake_scanner = MagicMock()
    fake_scanner._list = lambda *a, **kw: []
    fake_scanner._drive_service = capturing_drive_service
    fake_scanner.ACP = ROOT
    fake_scanner.FANOUT_MAX_FILES = 5000
    fake_scanner._scope_for_listing = lambda user: {}

    fake_rubric_mod = MagicMock()
    fake_rubric_mod.Rubric.load_active.return_value = _fake_rubric()

    payload = {
        "scan_id": "s_priority",
        "source": "drive",
        "user": "test@x.com",
        "drive_token": "PAYLOAD_CORRECT_TOKEN",
    }

    with patch.dict(sys.modules, {"scanner": fake_scanner, "rubric": fake_rubric_mod}):
        handlers._scan_discover(payload, {"scan_id": "s_priority"})

    assert received_token == ["PAYLOAD_CORRECT_TOKEN"], (
        f"_drive_service received {received_token!r}; payload token must take priority "
        "over any stale token that happens to be in the in-memory store"
    )


def test_in_memory_token_used_as_fallback(isolated_store, monkeypatch):
    """When the payload carries no token, fall back to the in-memory store.

    This preserves backward compatibility for same-replica deployments."""
    import core
    import handlers

    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setattr(core, "get_scan_tokens",
                        lambda sid: {"drive": "IN_MEMORY_FALLBACK"})
    monkeypatch.setattr(handlers, "_defer_analysis_to_assess", lambda: True)
    monkeypatch.setattr(handlers, "_enqueue_analysis", lambda *a, **kw: None)

    received_token = []

    def capturing_drive_service(tok):
        received_token.append(tok)
        return MagicMock()

    fake_scanner = MagicMock()
    fake_scanner._list = lambda *a, **kw: []
    fake_scanner._drive_service = capturing_drive_service
    fake_scanner.ACP = ROOT
    fake_scanner.FANOUT_MAX_FILES = 5000
    fake_scanner._scope_for_listing = lambda user: {}

    fake_rubric_mod = MagicMock()
    fake_rubric_mod.Rubric.load_active.return_value = _fake_rubric()

    # Payload has no drive_token.
    payload = {"scan_id": "s_fallback", "source": "drive", "user": "test@x.com"}

    with patch.dict(sys.modules, {"scanner": fake_scanner, "rubric": fake_rubric_mod}):
        handlers._scan_discover(payload, {"scan_id": "s_fallback"})

    assert received_token == ["IN_MEMORY_FALLBACK"], (
        f"_drive_service received {received_token!r}; in-memory token must be the fallback "
        "when no payload token is present"
    )


# ── Bug 3: stuck-at-zero loop ─────────────────────────────────────────────────

def test_second_scan_with_no_nonempty_baseline_retries_once(isolated_store, monkeypatch):
    """A scan for a source whose prior runs all returned 0 must retry once.

    Regression for the stuck-at-zero loop: after the first scan (and its first-scan retry) both
    returned 0, `_first_scan` is False (a prior run exists) but `_baseline_id` is None (no run
    ever found files). The old `if _first_scan:` guard silently accepted the zero on every
    subsequent scan. The fix is `if not _baseline_id:`, which retries regardless of whether this
    is literally the first scan or the tenth — as long as there is no proven non-empty baseline.

    This is safe: the retry is cheap, and accepting a zero without a baseline means the estate
    could be silently empty because of an API hiccup that happened to strike on every scan so far.
    """
    import core
    import handlers

    # Seed a prior scan that returned 0 files: _first_scan will be False (a previous run exists)
    # but last_nonempty_run_for_source returns None (no run ever had files).
    isolated_store.init_scan_run("prior-zero-scan", "drive", 0, "2026-01-01T00:00:00",
                                  "rb", "hash", owner="user@x.com", status="discovered")

    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setattr(core, "get_scan_tokens", lambda sid: {})
    monkeypatch.setattr(handlers, "_defer_analysis_to_assess", lambda: True)
    monkeypatch.setattr(handlers, "_enqueue_analysis", lambda *a, **kw: None)
    # Override the autouse fixture's suppression: this test IS about the no-baseline retry.
    # last_nonempty_run_for_source returns None because "prior-zero-scan" had 0 files.
    monkeypatch.setattr(isolated_store, "last_nonempty_run_for_source",
                        lambda *a, **kw: None, raising=False)

    list_call_count = []
    sleep_calls = []

    def counting_list(*args, **kwargs):
        list_call_count.append(1)
        return []

    fake_scanner = MagicMock()
    fake_scanner._list = counting_list
    fake_scanner._drive_service = lambda tok: MagicMock()
    fake_scanner.ACP = ROOT
    fake_scanner.FANOUT_MAX_FILES = 5000
    fake_scanner._scope_for_listing = lambda user: {}

    fake_rubric_mod = MagicMock()
    fake_rubric_mod.Rubric.load_active.return_value = _fake_rubric()

    import unittest.mock
    with patch.dict(sys.modules, {"scanner": fake_scanner, "rubric": fake_rubric_mod}):
        with unittest.mock.patch("time.sleep", lambda s: sleep_calls.append(s)):
            handlers._scan_discover(
                {"scan_id": "s_stuck_zero", "source": "drive", "user": "user@x.com",
                 "drive_token": "SOME_TOKEN"},
                {"scan_id": "s_stuck_zero"},
            )

    assert len(list_call_count) == 2, (
        f"_list was called {len(list_call_count)} time(s); expected 2 — "
        "a source with no non-empty baseline must retry once to rule out a transient API hiccup, "
        "even if it has been scanned before (second, third, … scan all returning 0)"
    )
    assert sleep_calls, "_scan_discover must sleep before the retry"
