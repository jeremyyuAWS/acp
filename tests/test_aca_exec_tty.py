"""The legacy probe must reach ACA from a non-interactive Actions runner."""
from __future__ import annotations

import base64
import gzip
import os
from pathlib import Path
import runpy
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def test_aca_exec_gets_a_tty_and_preserves_the_space_free_python_program(tmp_path):
    """Reproduce the two live failures: no runner TTY and ACA's whitespace-only command parser."""
    fake_az = tmp_path / "az"
    fake_az.write_text(
        """#!/usr/bin/env bash
set -eu
[ -t 0 ] || { echo 'stdin is not a tty' >&2; exit 71; }
# The Actions runner's stdin is EOF. A script(1) PTY forwards it and read returns 1 immediately;
# the dedicated runner keeps its master open, so this read waits and returns a timeout (>128).
set +e
started=$SECONDS
read -r -t 1
read_status=$?
elapsed=$((SECONDS - started))
set -e
[ "$read_status" -ne 0 ] && [ "$elapsed" -ge 1 ] \
  || { echo "pty input closed immediately: status=$read_status elapsed=$elapsed" >&2; exit 72; }
[ "$1 $2" = 'containerapp exec' ]
while [ "$#" -gt 0 ] && [ "$1" != '--command' ]; do shift; done
[ "$1" = '--command' ] && shift
[ "$1" = \"python -c exec(__import__('base64').b64decode('YWJj'))\" ]
printf 'INFO: Successfully connected to container\\n'
printf 'ACP_LEGACY_BOOTSTRAP={"redis_write_read":true,"queued":0,"retrying":0,"running":0}\\n'
printf 'INFO: received success status from cluster\\n'
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
        capture_output=True,
        env=env,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr.decode()
    assert b"ACP_LEGACY_BOOTSTRAP=" in result.stdout
    assert b"Successfully connected" in result.stdout
    assert b"\r\n" in result.stdout, "fixture must preserve the util-linux PTY transcript framing"


def test_redeploy_sends_no_quoted_python_c_program_to_aca():
    script = (ROOT / "deploy/public/redeploy.sh").read_text()
    gate = script[script.index("LEGACY_PROBE_B64="):script.index("BOOTSTRAP_REDIS BOOTSTRAP_QUEUED")]
    assert "_aca_exec_tty az containerapp exec" in gate
    assert "python -c exec(__import__('gzip').decompress(__import__('base64').b64decode(" in gate
    assert 'python -c \\"' not in gate


def test_probe_payload_fits_the_live_websocket_handshake_and_round_trips():
    source = (ROOT / "deploy/public/legacy_bootstrap_probe.py").read_bytes()
    payload = base64.b64encode(gzip.compress(source, mtime=0)).decode()
    command = (
        "python -c exec(__import__('gzip').decompress("
        f"__import__('base64').b64decode('{payload}')))"
    )

    # The 3,432-character raw command was rejected before Azure printed its connected banner;
    # the 1,457-character compressed command completed against that same live staging replica.
    assert len(command) < 1_800
    assert gzip.decompress(base64.b64decode(payload)) == source


def test_linux_transcript_marker_survives_a_nonzero_transport_exit(monkeypatch, capsys):
    """The live runner returned 1 during websocket teardown after the remote command completed."""
    transcript = (
        "INFO: Connecting to the container 'redacted'...\r\n"
        "\x1b[93mUse ctrl + D to exit.\x1b[0m\r\n"
        'ACP_LEGACY_BOOTSTRAP={"queued":0,"redis_write_read":true,'
        '"retrying":0,"running":0}\r\n'
        "INFO: received success status from cluster\r\n"
    )
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(transcript))

    runpy.run_path(str(ROOT / "scripts/parse_legacy_bootstrap.py"), run_name="__main__")

    assert capsys.readouterr().out == "true 0 0 0\n"
    script = (ROOT / "deploy/public/redeploy.sh").read_text()
    gate = script[script.index("LEGACY_PROBE_EXIT=0"):script.index("REDIS_CONFIGURED=true")]
    assert '|| LEGACY_PROBE_EXIT=$?' in gate
    assert "parse_legacy_bootstrap.py" in gate
    assert gate.index("parse_legacy_bootstrap.py") < gate.index('[ "$BOOTSTRAP_REDIS" = true ]')


def test_bootstrap_parser_rejects_missing_duplicate_and_malformed_markers():
    from scripts.parse_legacy_bootstrap import parse

    good = 'ACP_LEGACY_BOOTSTRAP={"redis_write_read":true,"queued":0,"retrying":0,"running":0}'
    assert parse("") is None
    assert parse(good + "\n" + good) is None
    assert parse("ACP_LEGACY_BOOTSTRAP={bad json}") is None
    assert parse('ACP_LEGACY_BOOTSTRAP={"redis_write_read":true,"queued":-1,"retrying":0,"running":0}') is None
