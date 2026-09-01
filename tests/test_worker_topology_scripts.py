from pathlib import Path


ROOT = Path(__file__).parents[1]
LANES = ("acp-discovery", "acp-assess", "acp-remediate")


def _read(path: str) -> str:
    return (ROOT / path).read_text()


def test_prebuilt_blue_green_updates_and_rolls_back_every_stage_worker():
    script = _read("deploy/blue-green.sh")
    assert 'LANE_WORKERS=("$DISCOVERY_WORKER" "$ASSESS_WORKER" "$REMEDIATE_WORKER")' in script
    assert 'for a in "${LANE_WORKERS[@]}"' in script
    for var in ("DISCOVERY_WORKER", "ASSESS_WORKER", "REMEDIATE_WORKER"):
        assert f'-n ${var} --image $BLUE_IMG' in script
    assert "ACP_WORKER:-acp-worker" not in script


def test_langfuse_cutover_defaults_to_app_and_all_stage_workers():
    script = _read("deploy/langfuse-v3/cutover.sh")
    for app in ("acp-app", *LANES):
        assert app in script
    assert "acp-app acp-worker" not in script


def test_start_all_uses_live_production_topology():
    script = _read("scripts/acp-start-all.sh")
    for app in ("acp-app", *LANES):
        assert app in script
    assert "acp-app acp-worker" not in script
