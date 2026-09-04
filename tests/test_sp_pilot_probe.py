import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import sp_pilot_probe as probe  # noqa: E402


def test_site_file_and_flags_are_deduplicated_in_selection_order(tmp_path):
    site_file = tmp_path / "sites.txt"
    site_file.write_text("# pilot sites\nS2\nS3\nS1\n")
    assert probe._site_ids(["S1", "S2"], str(site_file)) == ["S1", "S2", "S3"]


def test_probe_reports_complete_breadth_and_throttling(monkeypatch):
    def listing(token, max_files, sites, scope_out):
        assert token == "secret" and max_files == 500 and sites == ["S1", "S2"]
        scope_out.update({
            "sites": [
                {"id": "S1", "status": "complete", "listed": 1, "throttled": 2},
                {"id": "S2", "status": "complete", "listed": 1, "throttled": 0},
            ],
            "inventory": {"discovered": 2, "truncated": False},
        })
        return [{"id": "A"}, {"id": "B"}]
    monkeypatch.setattr(probe.scanner, "_sp_list", listing)

    out = probe.run_probe("secret", ["S1", "S2"], 500)

    assert out["complete"] is True
    assert out["requested_sites"] == out["reported_sites"] == 2
    assert out["documents_listed"] == 2
    assert out["throttled_retries"] == 2
    assert out["exceptions"] == []


@pytest.mark.parametrize("status", ["partial", "blocked", "skipped"])
def test_probe_fails_closed_for_any_site_exception(monkeypatch, status):
    monkeypatch.setattr(probe.scanner, "_sp_list", lambda token, max_files, sites, scope_out: (
        scope_out.update({"sites": [{"id": "S1", "status": status, "error": "denied"}],
                          "inventory": {"truncated": True}}) or []))
    out = probe.run_probe("secret", ["S1"], 10)
    assert out["complete"] is False
    assert out["exception_count"] == 1
    assert out["exceptions"][0]["status"] == status


def test_cli_never_accepts_a_token_argument(monkeypatch, capsys):
    monkeypatch.delenv("ACP_SP_TOKEN", raising=False)
    with pytest.raises(SystemExit) as exc:
        probe.main(["--site", "S1", "--token", "must-not-be-supported"])
    assert exc.value.code == 2
    assert "unrecognized arguments: --token" in capsys.readouterr().err


def test_cli_writes_machine_readable_evidence(monkeypatch, tmp_path):
    monkeypatch.setenv("ACP_SP_TOKEN", "secret")
    monkeypatch.setattr(probe.scanner, "_sp_max_sites", lambda: 30)
    monkeypatch.setattr(probe, "run_probe", lambda token, sites, max_files: {
        "complete": True, "requested_sites": 1, "sites": []})
    output = tmp_path / "evidence.json"

    assert probe.main(["--site", "S1", "--output", str(output)]) == 0
    assert json.loads(output.read_text())["complete"] is True
