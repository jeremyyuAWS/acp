"""The measured shadow comparison is compact, current, and safe to expose in governance."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_runtime_report_is_current_and_only_recommends_assisted_pilots():
    run = subprocess.run([sys.executable, "scripts/gen_shadow_rollout_status.py", "--check"],
                         cwd=ROOT, capture_output=True, text=True)
    assert run.returncode == 0, run.stdout + run.stderr
    report = json.loads((ROOT / "config/shadow-model-rollout.json").read_text())
    enabled = [r for r in report["rows"] if r["verdict"] == "enable"]
    assert {(r["format"], r["criterion"]) for r in enabled} == {
        ("docx", "2.4.4"), ("html", "2.4.4")}
    assert all(r["enable_candidate"] == "anthropic:claude-sonnet-5" for r in enabled)
    assert "human approval remains required" in report["decision_rule"]["enable"].lower()


def test_ai_cost_endpoint_attaches_report_without_fabricating_a_fallback():
    source = (ROOT / "api/routes/ai.py").read_text()
    assert '"shadow_rollout": shadow_rollout' in source
    assert "shadow_rollout = None" in source
