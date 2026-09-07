from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = (ROOT / ".github/workflows/validate-staging-scale-test.yml").read_text()


def test_targets_all_role_specific_staging_workers():
    for name in ("acp-discovery-staging", "acp-assess-staging", "acp-remediate-staging"):
        assert name in WORKFLOW
    assert "'acp-worker-staging'" not in WORKFLOW


def test_is_manual_confirmed_and_staging_guarded():
    assert "workflow_dispatch:" in WORKFLOW
    assert "inputs.confirm_scale_test" in WORKFLOW
    assert WORKFLOW.count("--check-staging-only") >= 2
    assert "ACP_CAPACITY_APPLY_ENABLED" not in WORKFLOW


def test_restores_complete_policy_even_after_failure():
    assert "--query properties.template.scale -o json > original-scale.json" in WORKFLOW
    assert "if: always() && steps.before.outputs.original_min != ''" in WORKFLOW
    assert '"scale": json.load(open("original-scale.json"))' in WORKFLOW
    assert "before == after" in WORKFLOW


def test_checks_limits_identity_and_rule_preservation():
    assert "STAGING_ACA_VCPU_QUOTA" in WORKFLOW
    assert "STAGING_PG_MAX_CONNECTIONS" in WORKFLOW
    assert "STAGING_PG_RESERVED_CONNECTIONS" in WORKFLOW
    assert "identity.principalId" in WORKFLOW
    assert "role assignment list" in WORKFLOW
    assert "Azure changed the existing rule array" in WORKFLOW


def test_staging_deploy_passes_capacity_gateway_inputs_to_redeploy():
    deploy = (ROOT / ".github/workflows/deploy-staging.yml").read_text()
    for name in ("STAGING_CAPACITY_APPLY_ENABLED", "STAGING_ACA_VCPU_QUOTA",
                 "STAGING_PG_MAX_CONNECTIONS", "STAGING_PG_RESERVED_CONNECTIONS"):
        assert name in deploy


def test_redeploy_stamps_gateway_settings_only_on_both_api_rollout_paths():
    script = (ROOT / "deploy/public/redeploy.sh").read_text()
    assert 'CAPACITY_APPLY_ENABLED=0' in script
    assert '[ "$DEPLOY_TARGET_ENV" = staging ] && [ "$CAPACITY_APPLY_REQUESTED" = 1 ]' in script
    assert '"WORKER_APP_NAMES=$DISCOVERY_WORKER,$ASSESS_WORKER,$REMEDIATE_WORKER"' in script
    assert script.count('--set-env-vars "${API_ENV_VARS[@]}"') == 2
    assert "ACP_PG_RESERVED_CONNECTIONS must be smaller" in script
    for worker_update in script.split('for a in "${LANE_WORKERS[@]}"; do')[1:3]:
        assert 'API_ENV_VARS' not in worker_update.split("done", 1)[0]
