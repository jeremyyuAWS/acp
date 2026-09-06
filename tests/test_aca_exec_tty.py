"""The legacy probe must reach ACA from a non-interactive Actions runner."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def test_aca_exec_gets_a_tty_and_preserves_the_space_free_python_program(tmp_path):
    """Reproduce the two live failures: no runner TTY and ACA's whitespace-only command parser."""
    fake_az = tmp_path / "az"
    fake_az.write_text(
        """#!/usr/bin/env bash
set -eu
[ -t 0 ] || { echo 'stdin is not a tty' >&2; exit 71; }
[ "$1 $2" = 'containerapp exec' ]
while [ "$#" -gt 0 ] && [ "$1" != '--command' ]; do shift; done
[ "$1" = '--command' ] && shift
[ "$1" = \"python -c exec(__import__('base64').b64decode('YWJj'))\" ]
printf 'ACP_LEGACY_BOOTSTRAP={"redis_write_read":true,"queued":0,"retrying":0,"running":0}\\n'
"""
    )
    fake_az.chmod(0o755)
    env = {**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}"}
    command = f"""
set -euo pipefail
source {ROOT / 'deploy/public/readiness_probe.sh'}
_aca_exec_tty az containerapp exec -g test-rg -n test-app \\
  --command \"python -c exec(__import__('base64').b64decode('YWJj'))\"
"""

    result = subprocess.run(
        ["bash", "-c", command],
        stdin=subprocess.DEVNULL,
        text=True,
        capture_output=True,
        env=env,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert "ACP_LEGACY_BOOTSTRAP=" in result.stdout


def test_redeploy_sends_no_quoted_python_c_program_to_aca():
    script = (ROOT / "deploy/public/redeploy.sh").read_text()
    gate = script[script.index("LEGACY_PROBE_B64="):script.index("LEGACY_PROBE_JSON=")]
    assert "_aca_exec_tty az containerapp exec" in gate
    assert "python -c exec(__import__('base64').b64decode(" in gate
    assert 'python -c \\"' not in gate
