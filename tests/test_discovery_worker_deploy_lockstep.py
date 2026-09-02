from pathlib import Path


def test_production_redeploy_updates_all_stage_workers_in_lockstep_without_shared_worker():
    script = (Path(__file__).parents[1] / "deploy/public/redeploy.sh").read_text()
    assert 'DISCOVERY_WORKER="${ACP_DISCOVERY_WORKER:-acp-discovery}"' in script
    assert 'ASSESS_WORKER="${ACP_ASSESS_WORKER:-acp-assess}"' in script
    assert 'REMEDIATE_WORKER="${ACP_REMEDIATE_WORKER:-acp-remediate}"' in script
    assert 'LANE_WORKERS=("$DISCOVERY_WORKER" "$ASSESS_WORKER" "$REMEDIATE_WORKER")' in script
    assert 'for a in "$APP" "${LANE_WORKERS[@]}"' in script
    assert 'for a in "${LANE_WORKERS[@]}"' in script
    assert 'ACP_WORKER:-acp-worker' not in script
