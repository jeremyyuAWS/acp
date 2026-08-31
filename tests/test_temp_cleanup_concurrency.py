"""Cleanup never deletes a LIVE session's files — asserted against a real concurrent process.

WHY THIS EXISTS SEPARATELY FROM test_temp_dir_hygiene.py. That file pins the within-session
rule: every xdist worker shares one directory, and retention counts only DEAD runs. It proves
that by inspecting the live session's own directory. What it never exercises is the case this
repo actually lives in — SEVERAL CONCURRENT PYTEST SESSIONS on one machine, each a separate
controller process with its own run directory, none of which can see the others' work.

That distinction matters because the two failure modes have different causes and the first fix
did not address the second. The xdist bug (418 errors across all four CI shards) was siblings
inside one session competing for a retention slot, fixed by sharing a directory. A concurrent
SESSION cannot share a directory — it legitimately needs its own — so it is protected only by
the liveness check, and nothing asserted that the liveness check works on a process that is not
this one.

Getting it wrong is not a housekeeping problem. Deleting a live session's temp directory makes
ITS tests fail, in another terminal, with FileNotFoundError on fixtures it created correctly —
a failure that reads as a bug in whatever that session was working on. CLAUDE.md records seven
concurrent sessions on this checkout on one day, and the disk-exhaustion incident that motivated
the whole redirect came from the same concurrency.

WHAT IS REAL HERE. The live process is a real subprocess, not a mocked pid: `os.kill(pid, 0)`
is asked about a process the kernel actually knows. The dead pid is real too — a subprocess that
has exited and been reaped. Nothing here monkeypatches `_acp_pid_alive`; that would assert the
test's model of liveness rather than the kernel's.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import conftest as acp_conftest  # noqa: E402


@pytest.fixture()
def live_pid():
    """A real, running process that is not this one."""
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        assert acp_conftest._acp_pid_alive(p.pid), "the fixture process must actually be alive"
        yield p.pid
    finally:
        p.kill()
        p.wait()


@pytest.fixture()
def dead_pid():
    """A real pid that has exited and been reaped."""
    p = subprocess.Popen([sys.executable, "-c", ""])
    p.wait()
    return p.pid


def _run_dir(root: Path, pid: int, *, age_s: float = 0.0) -> Path:
    d = root / f"run-{pid}-fixture{pid}"
    d.mkdir(parents=True)
    (d / "fixture.bin").write_bytes(b"a document another session is mid-way through building")
    if age_s:
        past = time.time() - age_s
        os.utime(d, (past, past))
    return d


@pytest.fixture()
def isolated_root(tmp_path, monkeypatch):
    """Point the claim logic at a throwaway root, and guarantee this session's own tempdir is
    restored afterwards — a test that leaves `tempfile.tempdir` moved would break every later
    test in the same worker."""
    root = tmp_path / "acp-pytest"
    root.mkdir()
    saved_tempdir = tempfile.tempdir
    monkeypatch.setattr(acp_conftest, "_TMP_ROOT", root)
    monkeypatch.delenv("ACP_PYTEST_TMP", raising=False)
    try:
        yield root
    finally:
        tempfile.tempdir = saved_tempdir


def test_a_live_concurrent_session_is_never_pruned(isolated_root, live_pid, dead_pid):
    """THE RULE, against a real running process.

    The root is stacked well past the retention cap with DEAD runs so that pruning definitely
    happens on this call — otherwise a passing result would be consistent with "nothing was
    deleted at all", which proves nothing about liveness.
    """
    live = _run_dir(isolated_root, live_pid)
    dead = [_run_dir(isolated_root, dead_pid + 1000 + i, age_s=60 * (i + 1)) for i in range(6)]

    acp_conftest._acp_claim_tmpdir()

    assert live.is_dir(), (
        "a CONCURRENT SESSION'S directory was deleted while its process was still running — "
        "that session's fixtures vanish mid-test and the failure surfaces in its terminal, not "
        "ours")
    assert (live / "fixture.bin").exists(), "its contents must be untouched, not just the dir"
    survivors = [d for d in dead if d.is_dir()]
    assert len(survivors) <= acp_conftest._TMP_KEEP_DEAD, (
        f"pruning did not actually run ({len(survivors)} of {len(dead)} dead dirs survived), so "
        f"this test proved nothing about the live one")


def test_many_live_sessions_all_survive_however_many_there_are(isolated_root):
    """Retention is a cap on DEAD runs, not on the total. Seven concurrent sessions is a real
    number for this checkout, and every one of them must keep its directory."""
    procs = [subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
             for _ in range(7)]
    try:
        dirs = [_run_dir(isolated_root, p.pid) for p in procs]
        acp_conftest._acp_claim_tmpdir()
        missing = [d.name for d in dirs if not d.is_dir()]
        assert missing == [], (
            f"{len(missing)} live sessions lost their directories: {missing}. Retention must "
            f"never bound the number of RUNNING sessions.")
    finally:
        for p in procs:
            p.kill()
            p.wait()


def test_the_claiming_session_gets_its_own_directory_and_publishes_it(isolated_root):
    """The other half: a concurrent session must not JOIN another session's directory either.
    Sharing is only ever within a session, via the inherited environment variable."""
    other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        theirs = _run_dir(isolated_root, other.pid)
        acp_conftest._acp_claim_tmpdir()
        claimed = Path(os.environ["ACP_PYTEST_TMP"])
        assert claimed != theirs, "claimed another live session's directory instead of its own"
        assert claimed.parent == isolated_root
        assert str(os.getpid()) in claimed.name, "the claim must be named for the claiming process"
        assert tempfile.tempdir == str(claimed)
    finally:
        other.kill()
        other.wait()


def test_an_xdist_worker_joins_rather_than_claiming(isolated_root, monkeypatch):
    """The within-session rule, restated here because the two rules are easy to conflate and
    fixing one is what broke the other. A process with ACP_PYTEST_TMP already set must reuse it
    and create nothing new."""
    session_dir = isolated_root / "run-999999-sessiondir"
    session_dir.mkdir()
    monkeypatch.setenv("ACP_PYTEST_TMP", str(session_dir))

    before = set(isolated_root.iterdir())
    acp_conftest._acp_claim_tmpdir()

    assert tempfile.tempdir == str(session_dir), "a worker must join the session's directory"
    assert set(isolated_root.iterdir()) == before, "a worker must not create a second directory"


def test_age_alone_never_condemns_a_live_run(isolated_root, live_pid, dead_pid):
    """THE DEFECT THIS FILE FOUND. The guard used to read `alive AND younger than 24h`, so a
    live session whose directory aged past the backstop became a deletion candidate — the exact
    outcome the mechanism exists to prevent.

    The reasoning behind the old condition was pid reuse: an ancient directory whose pid is alive
    is probably a different process by now. But that trade is backwards, and `_acp_pid_alive`
    already says so in its own docstring — a wrongly-kept directory costs disk, a wrongly-deleted
    one costs another session its run. Age now only ever condemns a run whose process is gone."""
    ancient_but_live = _run_dir(isolated_root, live_pid, age_s=48 * 3600)
    for i in range(5):
        _run_dir(isolated_root, dead_pid + 2000 + i, age_s=60 * (i + 1))

    acp_conftest._acp_claim_tmpdir()

    assert ancient_but_live.is_dir(), (
        "a live session was pruned for being old. Age may only ever condemn a run whose process "
        "is already gone.")


def test_age_still_condemns_a_dead_run_inside_the_keep_window(isolated_root, dead_pid):
    """The other side of the age rule, so the branch is not dead code.

    Retention keeps a couple of finished runs so a failure can be inspected. That is worth a few
    hours, not a few weeks — a dead run past `_TMP_MAX_AGE_S` is deleted even though it is one of
    the newest. Safe precisely because its process is already gone.
    """
    # Neighbouring PIDs may belong to live CI processes. Only the reaped PID is
    # known dead; create and reap a second process for the recent directory too.
    recent_process = subprocess.Popen([sys.executable, "-c", ""])
    recent_process.wait()
    assert not acp_conftest._acp_pid_alive(dead_pid)
    assert not acp_conftest._acp_pid_alive(recent_process.pid)
    ancient_dead = _run_dir(isolated_root, dead_pid, age_s=48 * 3600)
    recent_dead = _run_dir(isolated_root, recent_process.pid, age_s=60)

    acp_conftest._acp_claim_tmpdir()

    assert not ancient_dead.is_dir(), (
        "a dead run older than the age backstop survived — retention would grow without bound "
        "on a machine that never has more than _TMP_KEEP_DEAD finished runs at a time")
    assert recent_dead.is_dir(), (
        "a recent dead run was deleted — the keep window is what makes a failed run inspectable")
