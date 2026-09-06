"""Staging role workers must never resolve to production or retire their fallback early."""
from pathlib import Path
import os
import subprocess

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_staging_workflow_passes_every_role_name_and_environment_boundary():
    workflow = yaml.safe_load((ROOT / ".github/workflows/deploy-staging.yml").read_text())
    env = workflow["jobs"]["deploy"]["steps"][3]["env"]
    assert env["ACP_APP"].endswith("acp-app-staging' }}")
    assert env["ACP_DISCOVERY_WORKER"].endswith("acp-discovery-staging' }}")
    assert env["ACP_ASSESS_WORKER"].endswith("acp-assess-staging' }}")
    assert env["ACP_REMEDIATE_WORKER"].endswith("acp-remediate-staging' }}")
    assert env["ACP_DEPLOY_TARGET_ENV"] == "staging"
    assert "ACP_WORKER" not in env


def test_redeploy_rejects_staging_with_production_lane_defaults_before_azure():
    result = subprocess.run(
        ["bash", str(ROOT / "deploy/public/redeploy.sh")],
        cwd=ROOT,
        env={**os.environ, "ACP_DEPLOY_TARGET_ENV": "staging", "ACP_APP": "acp-app-staging"},
        text=True,
        capture_output=True,
        timeout=5,
    )
    assert result.returncode != 0
    assert "must end in -staging" in result.stderr
    assert "no active Azure subscription" not in result.stderr


def test_redeploy_rejects_duplicate_role_targets_before_azure():
    env = {
        **os.environ,
        "ACP_DEPLOY_TARGET_ENV": "staging",
        "ACP_APP": "acp-app-staging",
        "ACP_DISCOVERY_WORKER": "acp-discovery-staging",
        "ACP_ASSESS_WORKER": "acp-discovery-staging",
        "ACP_REMEDIATE_WORKER": "acp-remediate-staging",
    }
    result = subprocess.run(
        ["bash", str(ROOT / "deploy/public/redeploy.sh")], cwd=ROOT, env=env,
        text=True, capture_output=True, timeout=5,
    )
    assert result.returncode != 0
    assert "four distinct names" in result.stderr


def test_redeploy_checks_every_live_environment_stamp_before_build():
    script = (ROOT / "deploy/public/redeploy.sh").read_text()
    stamp = script.index("ACTUAL_DEPLOY_ENV=")
    build = script.index('say "building $IMG"')
    assert stamp < build
    block = script[script.rindex('for a in "$APP"', 0, stamp):script.index("# ── 1. pin", stamp)]
    assert 'for a in "$APP" "${LANE_WORKERS[@]}"' in block
    assert "expected '$DEPLOY_TARGET_ENV'" in block


def test_staging_provisioner_sets_roles_before_retiring_mixed_worker():
    script = (ROOT / "deploy/public/staging_up.sh").read_text()
    assert 'LANE_ROLES=(discovery assess remediate)' in script
    assert 'ACP_WORKER_ROLE="${LANE_ROLES[$i]}"' in script
    assert 'all(r.get(x,{}).get("alive") is True' in script
    proof = script.index('[ "$ROLES_READY" = true ]')
    retirement = script.index('--min-replicas 0 --max-replicas 1')
    assert proof < retirement
    assert "containerapp delete" not in script


def test_first_deploy_stamps_the_role_before_worker_startup():
    script = (ROOT / "deploy/public/deploy.sh").read_text()
    assert 'WORKER_ROLE_ENV="${ACP_WORKER_ROLE:+ACP_WORKER_ROLE=$ACP_WORKER_ROLE}"' in script
    worker = script[script.index('WORKER_APP="'):script.index("_apply_readiness_probe")]
    assert worker.count("$WORKER_ROLE_ENV ACP_WORKERS=$WK_N") == 2
    assert '--cpu "$WK_CPU" --memory "$WK_MEMORY"' in worker


def test_migration_overlap_stays_inside_one_cpu_until_legacy_retires():
    script = (ROOT / "deploy/public/staging_up.sh").read_text()
    assert 'ACP_WORKER_CPU="${ACP_STAGING_WORKER_CPU:-0.25}"' in script
    assert 'ACP_WORKER_MEMORY="${ACP_STAGING_WORKER_MEMORY:-0.5Gi}"' in script
    assert "ACP_WORKER_MIN_REPLICAS=1" in script
    assert script.index('ACP_WORKER_CPU="') < script.index('[ "$ROLES_READY" = true ]')


def test_manual_staging_start_targets_roles_not_retired_mixed_worker():
    workflow = (ROOT / ".github/workflows/start-staging-worker.yml").read_text()
    assert "acp-discovery-staging" in workflow
    assert "acp-assess-staging" in workflow
    assert "acp-remediate-staging" in workflow
    assert "acp-worker-staging" not in workflow
