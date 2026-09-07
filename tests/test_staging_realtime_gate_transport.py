from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

from scripts.parse_realtime_gate import MARKER, parse


ROOT = Path(__file__).resolve().parents[1]


def result(**overrides):
    value = {"decision": "GO", "mode": "redis", "config": {"redis_url": "configured"},
             "checks": {"latency": True, "isolation": True}}
    value.update(overrides)
    return value


def marker(value=None):
    return MARKER + json.dumps(value or result(), separators=(",", ":"))


def test_parser_accepts_one_go_marker_inside_a_pty_transcript():
    transcript = "INFO connected\r\n\x1b[32m" + marker() + "\x1b[0m\r\nteardown failed\r\n"
    assert parse(transcript)["decision"] == "GO"


def test_parser_rejects_missing_duplicate_malformed_and_no_go_markers():
    assert parse("") is None
    assert parse(marker() + "\n" + marker()) is None
    assert parse(MARKER + "{bad") is None
    assert parse(marker(result(decision="NO-GO"))) is None
    assert parse(marker(result(checks={"latency": False}))) is None
    assert parse(marker(result(config={"redis_url": "redis://secret"}))) is None


def test_workflow_uses_closed_stdin_safe_tty_and_parses_before_accepting_exit():
    workflow = (ROOT / ".github/workflows/validate-staging-realtime.yml").read_text()
    assert "_aca_exec_tty az containerapp exec" in workflow
    assert "python /app/scripts/staging_realtime_gate.py" in workflow
    parser = workflow.index("python3 scripts/parse_realtime_gate.py")
    warning = workflow.index("Azure exec exited")
    assert parser < warning


def test_tty_helper_survives_closed_stdin(tmp_path):
    child = tmp_path / "child.py"
    child.write_text("import os; assert os.isatty(0); print('TTY_OK')")
    completed = subprocess.run(
        ["python3", str(ROOT / "scripts/aca_exec_tty.py"), "--", "python3", str(child)],
        stdin=subprocess.DEVNULL, capture_output=True, env=os.environ, timeout=10,
    )
    assert completed.returncode == 0, completed.stderr.decode()
    assert b"TTY_OK" in completed.stdout
