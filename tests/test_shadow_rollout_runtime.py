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
    # The measured set on the 142-case run (one source report). It was {docx 2.4.4, html 2.4.4}
    # on the two 100-case runs; the other nine were withheld for under-sampling, not judged and
    # rejected. Re-pin this deliberately when the source report changes — never widen it.
    assert {(r["format"], r["criterion"]) for r in enabled} == {
        ("docx", "1.4.3"), ("docx", "1.4.5"), ("docx", "2.4.4"),
        ("html", "1.4.3"), ("html", "2.4.4"), ("html", "3.1.2"),
        ("pdf", "1.4.3"), ("pptx", "1.1.1"), ("pptx", "3.1.2"),
        ("xlsx", "1.1.1"), ("xlsx", "2.4.4")}
    assert all(r["enable_candidate"].startswith("anthropic:claude-") for r in enabled)
    assert "human approval remains required" in report["decision_rule"]["enable"].lower()


def test_the_panel_shows_candidate_safety_beside_the_rows_that_recommend_a_tier():
    """Sonnet is the enable candidate for five categories AND recorded a critical violation
    elsewhere in the same run. A panel that showed the first without the second would be
    recommending a tier while hiding what it did."""
    report = json.loads((ROOT / "config/shadow-model-rollout.json").read_text())
    safety = {c["candidate"]: c for c in report["candidate_safety"]}
    assert report["unmeasured_categories"], "a lane the run never saw must still be listed"
    recommended = {r["enable_candidate"] for r in report["rows"] if r["verdict"] == "enable"}
    assert recommended and recommended <= set(safety), "every recommended tier needs its record"
    sonnet = safety["anthropic:claude-sonnet-5"]
    assert sonnet["critical_violations"] == 1
    assert "no critical safety violations" in sonnet["gates_failed"]
    assert "anthropic:claude-sonnet-5" in recommended
    # Every tier still fails cost and autonomous-action precision; nothing here is an auto lane.
    for c in report["candidate_safety"]:
        assert "autonomous-action precision" in c["gates_failed"]


def test_the_evidence_block_states_the_replication_it_actually_has():
    report = json.loads((ROOT / "config/shadow-model-rollout.json").read_text())
    ev = report["evidence"]
    assert ev["independent_runs"] == len(ev["source_reports"]) >= 1
    # Derived, not pinned: it is the corpus the verdicts are judged against, which grows.
    import sys
    sys.path[:0] = [str(ROOT), str(ROOT / "api")]
    from evals.schema import load_cases
    assert ev["corpus_cases"] == len(load_cases())
    assert ("single run" in ev["replication"].lower()) == (ev["independent_runs"] == 1)


def test_ai_cost_endpoint_attaches_report_without_fabricating_a_fallback():
    source = (ROOT / "api/routes/ai.py").read_text()
    assert '"shadow_rollout": shadow_rollout' in source
    assert "shadow_rollout = None" in source
