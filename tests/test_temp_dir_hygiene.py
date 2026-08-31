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


def test_the_managed_root_keeps_only_a_few_runs():
    """Retention is what makes the growth bounded. Without it the redirect just moves the leak
    into a tidier directory."""
    root = Path(tempfile.gettempdir())
    while root.name != "acp-pytest" and root != root.parent:
        root = root.parent
    assert root.name == "acp-pytest", "the managed root should be an ancestor of tempdir"

    runs = [d for d in root.iterdir() if d.is_dir() and d.name.startswith("run-")]
    assert len(runs) <= 3, (
        f"{len(runs)} run directories are being kept. Retention is meant to hold the most "
        f"recent few so a failure can still be inspected; unbounded accumulation across runs "
        f"is exactly what filled the disk.")


def test_the_redirect_never_points_at_the_bare_system_temp():
    """The redirect must be a SUBDIRECTORY. Pointing `tempfile.tempdir` at the system temp
    itself, and pruning that, would delete other processes' state — a far worse bug than the
    leak, and the mistake a hurried fix would make."""
    assert tempfile.tempdir, "conftest should have set an explicit tempdir"
    td = Path(tempfile.tempdir).resolve()
    assert td != Path(tempfile.gettempdir()).resolve().parent
    assert "acp-pytest" in td.parts
    assert td.name.startswith("run-"), f"expected a per-run directory, got {td}"
    assert str(os.getpid()) in td.name, "the run directory should be per-process"
