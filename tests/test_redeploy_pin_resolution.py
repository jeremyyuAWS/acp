"""ACP_PIN must reach the CI gate as a full 40-char sha.

`gh run list --commit <sha>` matches ONLY the full sha — a short one returns no rows. The script
took ACP_PIN verbatim, so `ACP_PIN=1af3be9 ./redeploy.sh` died with:

    ✗ no CI run found for 1af3be9 — it may still be queued.

on a commit that existed and whose CI was green. The message names the wrong cause, and its
suggested remedy (ACP_SKIP_CI_GATE=1) resolves it by turning the gate off — so the failure mode
of a normalisation bug is a habit of deploying ungated. Hit twice on 2026-07-30, and it reaches
the pipeline too: .github/workflows/deploy.yml passes `ACP_PIN: ${{ inputs.pin }}` straight from
a human-typed workflow_dispatch field.

These run the real script with stubbed `az`/`gh` and let it die AT the gate, which is the whole
point of interest — nothing is cloned, built or deployed.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "deploy" / "public" / "redeploy.sh"


def _has_origin() -> bool:
    """The script fetches origin before resolving the pin, so a remote-less clone cannot run it."""
    r = subprocess.run(["git", "-C", str(REPO), "remote", "get-url", "origin"],
                       capture_output=True, text=True)
    return r.returncode == 0


requires_bash_and_origin = pytest.mark.skipif(
    not shutil.which("bash") or not SCRIPT.exists() or not _has_origin(),
    reason="needs bash, the script, and an origin remote to fetch")


def _stub_env(tmp_path, record: Path, **extra):
    """A PATH where `az` answers the subscription probe and `gh` records the sha it was given.

    The gh stub prints nothing for `run list`, which makes the script die at the gate immediately
    — before the isolated clone and the .NET build. What it recorded is the assertion.
    """
    binn = tmp_path / "bin"
    binn.mkdir(exist_ok=True)
    (binn / "az").write_text(
        "#!/usr/bin/env bash\n"
        "if [ \"$1\" = account ]; then echo 00000000-0000-0000-0000-000000000000; exit 0; fi\n"
        "echo 'STUB AZ CALLED BEYOND THE PIN STEP' >&2; exit 1\n")
    (binn / "gh").write_text(
        "#!/usr/bin/env bash\n"
        "if [ \"$1\" = auth ]; then exit 0; fi\n"
        "if [ \"$1\" = run ]; then\n"
        "  while [ $# -gt 0 ]; do\n"
        f"    if [ \"$1\" = --commit ]; then printf '%s' \"$2\" > {record}; fi\n"
        "    shift\n"
        "  done\n"
        "  exit 0\n"   # no rows -> the gate dies, which is where we want to stop
        "fi\n"
        "exit 0\n")
    for f in ("az", "gh"):
        (binn / f).chmod(0o755)
    env = dict(os.environ, PATH=f"{binn}:{os.environ['PATH']}", **extra)
    env.pop("ACP_SKIP_CI_GATE", None)
    return env


@requires_bash_and_origin
def test_a_short_pin_reaches_the_ci_gate_as_a_full_sha(tmp_path):
    full = subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"],
                          capture_output=True, text=True, check=True).stdout.strip()
    record = tmp_path / "seen"
    out = subprocess.run(["bash", str(SCRIPT)], capture_output=True, text=True,
                         env=_stub_env(tmp_path, record, ACP_PIN=full[:7]),
                         stdin=subprocess.DEVNULL, cwd=str(REPO))
    assert record.exists(), f"the CI gate never ran:\n{out.stdout}\n{out.stderr}"
    seen = record.read_text().strip()
    assert seen == full, f"gh was handed {seen!r}, not the full sha {full!r}"
    assert len(seen) == 40
    # and it never got far enough to touch Azure for real
    assert "STUB AZ CALLED BEYOND THE PIN STEP" not in out.stderr, out.stderr


@requires_bash_and_origin
def test_a_pin_that_is_not_a_commit_says_so_instead_of_blaming_ci(tmp_path):
    """The old code could not tell a typo from a queued build: both arrived at the gate and came
    back as 'no CI run found', pointing the operator at CI for a ref that never existed."""
    record = tmp_path / "seen"
    out = subprocess.run(["bash", str(SCRIPT)], capture_output=True, text=True,
                         env=_stub_env(tmp_path, record, ACP_PIN="no-such-ref-here"),
                         stdin=subprocess.DEVNULL, cwd=str(REPO))
    assert out.returncode != 0
    combined = out.stdout + out.stderr
    assert "cannot resolve" in combined, combined
    assert "no CI run found" not in combined, combined
    assert not record.exists(), "an unresolvable ref must never reach the CI gate"
