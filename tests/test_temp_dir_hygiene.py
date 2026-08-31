"""The suite's temporary files land somewhere that gets cleaned up.

WHY THIS IS A TEST AND NOT JUST A CONFTEST LINE. The leak it guards is invisible while it is
happening: every test passes, nothing warns, and the only symptom arrives much later as a full
disk — at which point writes fail while deletes still succeed, so the suite reports errors that
look like code faults and are not. On 2026-08-31 that cost a session its disk (30 GB across
eight full-suite runs) and, in clearing it, the environment's commit-signing helper.

139 call sites across ~60 modules build fixtures with a bare `tempfile.mkdtemp()`, which never
cleans up. `tests/conftest.py` redirects `tempfile.tempdir` at import so all of them land under
one root with bounded retention. A future conftest edit that drops that redirect would restore
the leak silently; this fails instead.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path


def test_mkdtemp_lands_under_the_managed_root():
    """A bare mkdtemp — the pattern the whole suite uses — must not land in the bare system
    temp directory, where nothing will ever remove it."""
    d = Path(tempfile.mkdtemp())
    try:
        assert "acp-pytest" in d.parts, (
            f"mkdtemp() produced {d}, which is outside the managed root. The conftest "
            f"redirect is gone, and every fixture directory this suite creates is now "
            f"permanently leaked.")
    finally:
        d.rmdir()


def _managed_root() -> Path:
    root = Path(tempfile.gettempdir())
    while root.name != "acp-pytest" and root != root.parent:
        root = root.parent
    assert root.name == "acp-pytest", "the managed root should be an ancestor of tempdir"
    return root


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


def test_only_finished_runs_are_ever_pruned():
    """Retention bounds the growth, but it may only ever reclaim a run whose process has
    EXITED.

    The first version of this guard asserted a flat cap of three directories. That encoded the
    wrong model and is what produced the bug: under `pytest -n auto` a shard is several worker
    processes, each took its own directory, and the fourth to start deleted the first's while
    it was still writing into it — 418 errors across all four CI shards. A live run is never a
    deletion candidate, however many are running at once, so the honest assertion is about
    DEAD directories, not about the total."""
    root = _managed_root()
    runs = [d for d in root.iterdir() if d.is_dir() and d.name.startswith("run-")]
    dead = [d for d in runs if not _alive(int(d.name.split("-")[1]))]
    assert len(dead) <= 3, (
        f"{len(dead)} finished run directories are being kept. Retention holds a couple so a "
        f"failure can still be inspected; unbounded accumulation is what filled the disk.")


def test_every_worker_in_this_session_shares_one_directory():
    """THE REGRESSION, pinned. `tempfile.tempdir` must belong to a directory claimed by a LIVE
    process — the session's controller — and every xdist worker must inherit that same one
    rather than claiming its own.

    Asserting "the directory contains MY pid" is what the broken version did, and it is false
    for a worker by design: the directory is per-SESSION, so its pid is the controller's."""
    td = Path(tempfile.tempdir).resolve()
    owner = int(td.name.split("-")[1])
    assert _alive(owner), (
        f"the run directory {td.name} names a dead process — it is not this session's, and "
        f"something else may prune it while these tests are still writing into it")
    assert os.environ.get("ACP_PYTEST_TMP") == str(td), (
        "the session directory must be published in the environment so xdist workers inherit "
        "it instead of each claiming their own")


def test_the_redirect_never_points_at_the_bare_system_temp():
    """The redirect must be a SUBDIRECTORY. Pointing `tempfile.tempdir` at the system temp
    itself, and pruning that, would delete other processes' state — a far worse bug than the
    leak, and the mistake a hurried fix would make. It is also what destroyed this
    environment's commit-signing helper on 2026-08-31."""
    assert tempfile.tempdir, "conftest should have set an explicit tempdir"
    td = Path(tempfile.tempdir).resolve()
    assert td != Path(tempfile.gettempdir()).resolve().parent
    assert "acp-pytest" in td.parts
    assert td.name.startswith("run-"), f"expected a per-run directory, got {td}"
