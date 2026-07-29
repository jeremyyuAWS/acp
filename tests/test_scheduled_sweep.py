"""A scheduled sweep must obey the setting, and must never substitute a different corpus.

Both defects were observed in production on 2026-07-29, five minutes apart, forever:

    scheduled sweep fell back to local (1 files); drive error: <HttpError 403 ...
    "Request had insufficient authentication scopes.">

Two separate bugs in one line of log.

1. IT COULD NOT BE TURNED OFF. `PUT /schedule` calls `reload_scheduler()` in whichever process
   served the request. Only `acp-app` has ingress, so that is the only process it can reach —
   while `worker_main.py:49-50` arms its own scheduler with this same job. Toggling the schedule
   off in the UI left the other copy running until the container restarted. Observed: six
   consecutive 5-minute sweeps (18:48:40 → 19:13:40 UTC) straight through a UI toggle.

2. IT REPLACED THE ESTATE WITH THE SAMPLES. On failure it ran `local` instead and saved AND
   finalized that as a scan. Every "latest" view reads `scan_runs ORDER BY completed_at DESC`,
   so a 1-file scan of the bundled corpus displaced a 258-document Drive estate — on the
   dashboard, in the report, and in the scan selector — every five minutes.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))


@pytest.fixture()
def core_mod(monkeypatch):
    import core
    calls = {"scans": [], "saved": 0, "finalized": 0, "reloads": 0}

    class _Store:
        def __init__(self): self.schedule = {"enabled": True, "interval_minutes": 5,
                                             "owner_email": "a@b.c", "source": "drive"}
        def get_schedule(self): return dict(self.schedule)
        def get_ai_enabled(self): return False
        def save_scan(self, report): calls["saved"] += 1; return "sid-1"

    store = _Store()
    monkeypatch.setattr(core, "get_store", lambda: store)
    monkeypatch.setattr(core, "finalize_scan", lambda *a, **k: calls.__setitem__("finalized", calls["finalized"] + 1))
    monkeypatch.setattr(core, "reload_scheduler", lambda: calls.__setitem__("reloads", calls["reloads"] + 1))

    def _scan(src, **kw):
        calls["scans"].append(src)
        if src == "drive":
            raise RuntimeError("HttpError 403 ... Request had insufficient authentication scopes.")
        return {"summary": {"files": 1}}

    monkeypatch.setattr(core, "run_scan", _scan)
    return core, store, calls


# ── 1. the setting is authoritative on every fire ─────────────────────────────────────

def test_a_disabled_schedule_runs_nothing(core_mod):
    core, store, calls = core_mod
    store.schedule["enabled"] = False
    core._do_scheduled_scan()
    assert calls["scans"] == [], "a disabled schedule must not scan anything"
    assert calls["saved"] == 0


def test_a_disabled_schedule_disarms_the_job_in_this_process(core_mod):
    """The self-heal. Without it the stale job keeps firing every interval forever — it would
    just do nothing each time, which is correct but wasteful and hides the misconfiguration."""
    core, store, calls = core_mod
    store.schedule["enabled"] = False
    core._do_scheduled_scan()
    assert calls["reloads"] == 1


def test_the_check_is_re_read_not_cached(core_mod):
    """The whole point: a process that armed the job while enabled must notice it was turned
    off elsewhere. This is the worker's case, which no reload_scheduler() call can reach."""
    core, store, calls = core_mod
    store.schedule["source"] = "local"
    core._do_scheduled_scan()
    assert calls["scans"] == ["local"]          # armed and enabled — it runs
    store.schedule["enabled"] = False           # turned off in another container
    core._do_scheduled_scan()
    assert calls["scans"] == ["local"], "the second fire must read the setting again and stop"


# ── 2. a failed sweep saves nothing ───────────────────────────────────────────────────

def test_a_drive_failure_does_not_substitute_the_local_corpus(core_mod):
    core, store, calls = core_mod
    core._do_scheduled_scan()
    assert calls["scans"] == ["drive"], "it must not run a second scan against a different source"
    assert calls["saved"] == 0, "a failed sweep must not save a scan"
    assert calls["finalized"] == 0, "and must certainly not finalize one"


def test_a_failed_sweep_says_so_and_names_the_error(core_mod, capsys):
    core, store, calls = core_mod
    core._do_scheduled_scan()
    out = capsys.readouterr().out
    assert "FAILED" in out
    assert "previous scan stands" in out
    assert "403" in out, "the underlying cause must survive into the log, not be swallowed"


def test_a_failed_sweep_does_not_raise(core_mod):
    """APScheduler would log a job exception and keep going, but a raising job is noise in the
    logs and, with max_instances=1, risks masking the next fire."""
    core, store, calls = core_mod
    core._do_scheduled_scan()   # must not raise


# ── the happy path still works ────────────────────────────────────────────────────────

def test_a_working_sweep_scans_saves_and_finalizes_once(core_mod):
    core, store, calls = core_mod
    store.schedule["source"] = "local"
    core._do_scheduled_scan()
    assert calls["scans"] == ["local"]
    assert (calls["saved"], calls["finalized"]) == (1, 1)


def test_the_owner_is_carried_through_so_the_scan_is_attributable(core_mod, capsys):
    core, store, calls = core_mod
    store.schedule["source"] = "local"
    core._do_scheduled_scan()
    assert "owner=a@b.c" in capsys.readouterr().out
