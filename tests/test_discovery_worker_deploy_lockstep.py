from pathlib import Path


def test_production_redeploy_updates_dedicated_discovery_worker_in_lockstep():
    script = (Path(__file__).parents[1] / "deploy/public/redeploy.sh").read_text()
    assert 'DISCOVERY_WORKER="${ACP_DISCOVERY_WORKER:-acp-discovery}"' in script
    assert '-n "$DISCOVERY_WORKER" --image "$IMG" --no-wait' in script
    assert 'for a in "$APP" "$WORKER" "$DISCOVERY_WORKER"' in script
    assert 'for a in "$WORKER" "$DISCOVERY_WORKER"' in script
