"""The read_timings CLI helper (ADR 0037 Step 0). Pure parts only — URL/header resolution, the
formatting, and picking the latest scan — so the measure-first output is exercised without a server."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import read_timings as rt  # noqa: E402


def test_base_url_resolves_and_normalizes(monkeypatch):
    monkeypatch.delenv("ACP_BASE_URL", raising=False)
    monkeypatch.delenv("ACP_FQDN", raising=False)
    assert rt.base_url(None) == rt._PROD                            # default: prod
    assert rt.base_url("https://x.example/") == "https://x.example"  # trailing slash trimmed
    assert rt.base_url("host.example") == "https://host.example"     # bare host → https
    monkeypatch.setenv("ACP_FQDN", "envhost.example")
    assert rt.base_url(None) == "https://envhost.example"            # env fallback


def test_auth_headers_provider_hint():
    assert rt.auth_headers("tok", "google") == {"Authorization": "Bearer tok"}
    h = rt.auth_headers("tok", "microsoft")
    assert h["X-Auth-Provider"] == "microsoft" and h["Authorization"] == "Bearer tok"


def test_format_orders_by_time_marks_the_bottleneck_and_shows_shares():
    rollup = {"totals_s": {"download": 30.0, "analyse": 90.0}, "counts": {"download": 50, "analyse": 50},
              "avg_s": {"download": 0.6, "analyse": 1.8}, "bottleneck": "analyse", "files_timed": 50}
    out = rt.format_timings(rollup, "scan123")
    assert "scan123" in out and "files timed: 50" in out
    # analyse (bigger total) is listed first and starred; shares are 75% / 25%.
    lines = [l for l in out.splitlines() if l.strip().startswith(("analyse", "download"))]
    assert lines[0].strip().startswith("analyse") and "bottleneck" in lines[0]
    assert "75%" in lines[0] and "25%" in lines[1]
    assert "split into its own" in out                              # the ADR 0037 recommendation


def test_format_is_honest_when_nothing_was_measured():
    out = rt.format_timings({"totals_s": {}, "files_timed": 0})
    assert "nothing measured yet" in out
    assert "before this shipped" in out                            # never invents a bottleneck
    assert rt.format_timings(None).splitlines()[0] == "Stage timings"


def test_latest_scan_id_picks_the_first_row(monkeypatch):
    monkeypatch.setattr(rt, "_get", lambda *a, **k: [{"id": "newest"}, {"id": "older"}])
    assert rt.latest_scan_id("http://x", "t", "google") == "newest"
    # Also tolerates a {scans:[...]} wrapper and a nested run.id, and None when empty.
    monkeypatch.setattr(rt, "_get", lambda *a, **k: {"scans": [{"run": {"id": "r1"}}]})
    assert rt.latest_scan_id("http://x", "t", "google") == "r1"
    monkeypatch.setattr(rt, "_get", lambda *a, **k: [])
    assert rt.latest_scan_id("http://x", "t", "google") is None


def test_main_refuses_without_a_token(monkeypatch, capsys):
    monkeypatch.delenv("ACP_TOKEN", raising=False)
    assert rt.main([]) == 2
    assert "no token" in capsys.readouterr().err
