"""The production monitor must fire on the failures that actually happened.

A monitor is only worth its cron slot if it catches the thing that went wrong. These tests replay
2026-07-29's silent failures as data and assert the check goes red — because a monitor that
reports green through an outage is worse than none, and the only way to know which one you have
is to make it fail on purpose.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import monitor as M  # noqa: E402


@pytest.fixture()
def rep():
    return M.Report()


def _stub(monkeypatch, payload, code=200):
    monkeypatch.setattr(M, "get", lambda url, key=None, timeout=20: (code, json.dumps(payload), 5.0))


def scans(*counts):
    """Newest first, exactly as list_scans orders them."""
    return [{"id": f"s{i}", "files": n, "completed_at": f"2026-07-29T{10+i:02d}:00:00Z"}
            for i, n in enumerate(counts)]


# ── the sweep collapse ────────────────────────────────────────────────────────────────

def test_a_one_file_scan_landing_on_a_258_file_estate_fires(monkeypatch, rep):
    """The exact shape of the bug: a fallback sweep of the bundled corpus saved and finalized on
    top of the real estate, so every 'latest' view showed 1 document instead of 258."""
    _stub(monkeypatch, scans(1, 258, 258, 257))
    M.check_scan_scale("https://x", "k", rep)
    assert rep.failed == 1
    assert "newest has 1 documents but a recent scan had 258" in rep.rows[-1][2]


def test_a_full_size_newest_scan_passes(monkeypatch, rep):
    _stub(monkeypatch, scans(258, 258, 257))
    M.check_scan_scale("https://x", "k", rep)
    assert rep.failed == 0


def test_ordinary_estate_growth_and_shrinkage_does_not_fire(monkeypatch, rep):
    """Documents get added and removed. Only a COLLAPSE is a signal — a monitor that cries on
    normal variation gets muted, and a muted monitor is the same as no monitor."""
    _stub(monkeypatch, scans(240, 258, 251, 262))
    M.check_scan_scale("https://x", "k", rep)
    assert rep.failed == 0


def test_a_first_ever_scan_does_not_fire(monkeypatch, rep):
    _stub(monkeypatch, scans(12))
    M.check_scan_scale("https://x", "k", rep)
    assert rep.failed == 0


def test_no_completed_scans_is_a_failure_not_a_pass(monkeypatch, rep):
    _stub(monkeypatch, [])
    M.check_scan_scale("https://x", "k", rep)
    assert rep.failed == 1


def test_a_rejected_key_fails_rather_than_silently_skipping(monkeypatch, rep):
    """401 must not read as 'nothing to report'. This is the failure mode that makes a monitor
    lie: the deep checks stop running and the summary still says green."""
    monkeypatch.setattr(M, "get", lambda *a, **k: (401, "unauthorized", 5.0))
    M.check_scan_scale("https://x", "k", rep)
    assert rep.failed == 1


# ── health / readiness ────────────────────────────────────────────────────────────────

def test_an_unstamped_build_fails(monkeypatch, rep):
    """An image built without the build args runs perfectly well while every surface reports
    version 'dev'. redeploy.sh refuses to ship one; this catches one that got there anyway."""
    _stub(monkeypatch, {"ok": True, "version": "dev", "version_stamped": False})
    M.check_health("https://x", rep)
    assert any(r[0] == "FAIL" and r[1] == "build is stamped" for r in rep.rows)


def test_a_dead_worker_tier_fails(monkeypatch, rep):
    """Scanning happens in the worker. A dead one means scans queue forever while the app looks
    perfectly healthy from the front."""
    _stub(monkeypatch, {"ready": True, "degraded": [], "engines": {"pdf": {"available": True}},
                        "workers": {"alive": False, "age_s": 9999}})
    M.check_ready("https://x", rep)
    assert any(r[0] == "FAIL" and r[1] == "worker tier alive" for r in rep.rows)


def test_a_stale_heartbeat_fails_even_when_alive_is_true(monkeypatch, rep):
    _stub(monkeypatch, {"ready": True, "degraded": [], "engines": {"pdf": {"available": True}},
                        "workers": {"alive": True, "age_s": M.HEARTBEAT_MAX_AGE_S + 1}})
    M.check_ready("https://x", rep)
    assert any(r[0] == "FAIL" and r[1] == "worker tier alive" for r in rep.rows)


def test_a_missing_pdf_engine_fails(monkeypatch, rep):
    _stub(monkeypatch, {"ready": True, "degraded": [], "workers": {"alive": True, "age_s": 1},
                        "engines": {"pdf": {"available": False, "reason": "not importable"}}})
    M.check_ready("https://x", rep)
    assert any(r[0] == "FAIL" and r[1] == "pdf engine loaded" for r in rep.rows)


def test_degraded_subsystems_fail(monkeypatch, rep):
    _stub(monkeypatch, {"ready": True, "degraded": ["blob_store"], "workers": {"alive": True, "age_s": 1},
                        "engines": {"pdf": {"available": True}}})
    M.check_ready("https://x", rep)
    assert any(r[0] == "FAIL" and r[1] == "nothing degraded" for r in rep.rows)


def test_an_unreachable_app_fails_instead_of_raising(monkeypatch, rep):
    """A monitor must report a failure, never become one."""
    monkeypatch.setattr(M, "get", lambda *a, **k: (0, "connection refused", 5.0))
    M.check_health("https://x", rep)
    assert rep.failed == 1


# ── the report contract ───────────────────────────────────────────────────────────────

def test_exit_code_is_nonzero_when_anything_failed(rep, capsys):
    rep.ok("a"); rep.fail("b", "because")
    assert rep.render() == 1
    assert "::error" in capsys.readouterr().out          # surfaces in the Actions run summary


def test_skips_do_not_turn_the_run_green_by_accident(rep, capsys):
    """A skip is not a pass. It must be visible in the output and counted separately, so a run
    where the deep checks never executed cannot be mistaken for one where they passed."""
    rep.ok("a"); rep.skip("deep check", "no key")
    assert rep.render() == 0
    out = capsys.readouterr().out
    assert "skip" in out and "1 skipped" in out
