"""Production deploys must not replace queue workers underneath live customer work."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_readyz_exposes_only_aggregate_durable_queue_activity():
    text = (ROOT / "api/routes/system.py").read_text()
    assert "core.store.job_stats(owner=None)" in text
    assert '"active"' in text and '"available"' in text
    assert '"payload"' not in text[text.index("_queue_stats ="):text.index("except Exception as exc", text.index("_queue_stats ="))]


def test_redeploy_refuses_when_queue_state_is_unknown_or_active():
    text = (ROOT / "deploy/public/redeploy.sh").read_text()
    gate = text.index('READY_BEFORE=')
    first_mutation = text.index('if [ "$BG" = 1 ]', gate)
    block = text[gate:first_mutation]
    assert "QUEUE_AVAILABLE" in block
    assert "ACTIVE_JOBS" in block
    assert "die " in block
    assert "ACP_DEPLOY_WITH_ACTIVE_JOBS" in block


def test_emergency_override_is_explicitly_manual_in_the_workflow():
    workflow = (ROOT / ".github/workflows/deploy.yml").read_text()
    assert "deploy_with_active_jobs:" in workflow
    assert "ACP_DEPLOY_WITH_ACTIVE_JOBS:" in workflow
    assert "Emergency only" in workflow
