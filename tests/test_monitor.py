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


def estate(*counts, pending=0):
    """A /monitor/estate payload. Counts are newest first, as list_scans orders them."""
    return {"service": "acp",
            "scans": {"total": len(counts), "recent_files": list(counts)},
            "inbox": {"pending": pending}}


# ── the sweep collapse ────────────────────────────────────────────────────────────────

def test_a_one_file_scan_landing_on_a_258_file_estate_fires(monkeypatch, rep):
    """The exact shape of the bug: a fallback sweep of the bundled corpus saved and finalized on
    top of the real estate, so every 'latest' view showed 1 document instead of 258."""
    _stub(monkeypatch, estate(1, 258, 258, 257))
    M.check_estate("https://x", "k", rep)
    assert rep.failed == 1
    assert any("newest has 1 documents but a recent scan had 258" in r[2] for r in rep.rows)


def test_a_full_size_newest_scan_passes(monkeypatch, rep):
    _stub(monkeypatch, estate(258, 258, 257))
    M.check_estate("https://x", "k", rep)
    assert rep.failed == 0


def test_ordinary_estate_growth_and_shrinkage_does_not_fire(monkeypatch, rep):
    """Documents get added and removed. Only a COLLAPSE is a signal — a monitor that cries on
    normal variation gets muted, and a muted monitor is the same as no monitor."""
    _stub(monkeypatch, estate(240, 258, 251, 262))
    M.check_estate("https://x", "k", rep)
    assert rep.failed == 0


def test_a_first_ever_scan_does_not_fire(monkeypatch, rep):
    _stub(monkeypatch, estate(12))
    M.check_estate("https://x", "k", rep)
    assert rep.failed == 0


def test_no_completed_scans_is_a_failure_not_a_pass(monkeypatch, rep):
    _stub(monkeypatch, estate())
    M.check_estate("https://x", "k", rep)
    assert rep.failed == 1


def test_the_backlog_is_reported(monkeypatch, rep):
    _stub(monkeypatch, estate(258, 258, pending=17))
    M.check_estate("https://x", "k", rep)
    assert rep.failed == 0
    assert any("17 pending review items" in r[2] for r in rep.rows)


# ── the deep tier's own auth, which is the part that was broken ───────────────────────

def test_a_rejected_key_fails_rather_than_silently_skipping(monkeypatch, rep):
    """401 must not read as 'nothing to report'. This is the failure mode that makes a monitor
    lie: the deep checks stop running and the summary still says green."""
    monkeypatch.setattr(M, "get", lambda *a, **k: (401, "bad monitor key", 5.0))
    M.check_estate("https://x", "k", rep)
    assert rep.failed == 1
    assert "key here and the key on the deployment differ" in rep.rows[-1][2]


def test_an_unconfigured_deployment_fails_and_says_which_side_is_missing(monkeypatch, rep):
    """503 means the DEPLOYMENT has no ACP_MONITOR_KEY, which is a different fix from a wrong
    key (401) and from a moved route (404). This is the case the old design could never even
    report: with the X-E2E-Key bypass disabled in production it got a flat 401 and no way to
    tell 'refused' from 'not configured'."""
    monkeypatch.setattr(M, "get", lambda *a, **k: (503, "monitoring is not configured", 5.0))
    M.check_estate("https://x", "k", rep)
    assert rep.failed == 1
    assert "not set ON THE DEPLOYMENT" in rep.rows[-1][2]


def test_the_deep_tier_sends_its_own_header_not_the_gate_bypass(monkeypatch):
    """The credential must be X-Monitor-Key. Sending X-E2E-Key is what made the deep checks
    unrunnable in production, and it is an easy thing to reintroduce by copy-paste."""
    seen = {}

    class _Resp:
        status = 200
        def read(self): return b"{}"
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def fake_urlopen(req, timeout=20):
        seen.update(req.headers)
        return _Resp()

    monkeypatch.setattr(M.urllib.request, "urlopen", fake_urlopen)
    M.get("https://x/monitor/estate", key="sekrit")
    # urllib title-cases header names.
    assert seen.get("X-monitor-key") == "sekrit"
    assert not any(k.lower() == "x-e2e-key" for k in seen)


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


# ── deploy drift: is the code everyone is reading the code that is running? ────────────

def _repo(tmp_path):
    """A real git repo with a real `origin`, because this check's whole job is to read git.

    Stubbing git here would test the stub. The failures this check exists to catch — a sha that
    is not in history, a commit that merged before the build clock — only exist as git state.
    """
    import subprocess as sp

    def run(cwd, *args, when=None):
        env = None
        if when:
            env = {**os.environ, "GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when}
        return sp.run(["git", "-C", str(cwd), *args], check=True, capture_output=True,
                      text=True, env=env).stdout.strip()

    bare, work = tmp_path / "origin.git", tmp_path / "work"
    sp.run(["git", "init", "--bare", "-b", "main", str(bare)], check=True, capture_output=True)
    sp.run(["git", "clone", str(bare), str(work)], check=True, capture_output=True)
    run(work, "config", "user.email", "t@t"); run(work, "config", "user.name", "t")

    def commit(msg, when):
        (work / "f").write_text(msg)
        run(work, "add", "f")
        run(work, "commit", "-m", msg, when=when)
        return run(work, "rev-parse", "HEAD")

    return work, commit, (lambda: run(work, "push", "-q", "origin", "main"))


import os  # noqa: E402  — used by _repo's date injection


def test_the_timestamp_check_undercounts_and_the_sha_check_does_not(tmp_path, rep):
    """The 2026-07-30 shape, replayed as data.

    A commit merged at 13:41:35Z. The running image was built two minutes LATER, at 13:43:34Z,
    but from an earlier pin — so that commit is on main and not in the image. `--since=built_at`
    cannot see it. This is the whole reason /healthz carries a commit sha.
    """
    work, commit, push = _repo(tmp_path)
    deployed = commit("the pinned commit", "2026-07-30T13:30:00+0000")
    commit("merged BEFORE the build clock, absent from the image", "2026-07-30T13:41:35+0000")
    commit("merged after", "2026-07-30T14:10:00+0000")
    push()
    health = {"commit": deployed, "built_at": "2026-07-30T13:43:34Z"}

    M.check_deploy_drift(health, str(work), rep)
    row = next(r for r in rep.rows if r[1] == "production is current")
    assert row[0] == "FAIL"
    assert "2 commit(s)" in row[2]          # the sha knows about both

    # The same estate read by timestamp alone sees only one of them.
    rep2 = M.Report()
    M.check_deploy_drift({"built_at": "2026-07-30T13:43:34Z"}, str(work), rep2)
    assert any("at least 1 commit(s)" in r[2] for r in rep2.rows)


def test_a_deployed_sha_level_with_main_passes(tmp_path, rep):
    work, commit, push = _repo(tmp_path)
    sha = commit("only commit", "2026-07-30T13:30:00+0000")
    push()
    M.check_deploy_drift({"commit": sha, "built_at": "2026-07-30T13:43:34Z"}, str(work), rep)
    assert rep.failed == 0
    assert any("level with main" in r[2] for r in rep.rows)


def test_an_image_built_from_a_sha_not_in_history_fails(tmp_path, rep):
    """docs/pipeline.md, guard 1: 2553e6d was in production and absent from git history. The
    dangerous answer here is '0 commits behind' — it is technically true and completely wrong."""
    work, commit, push = _repo(tmp_path)
    commit("real", "2026-07-30T13:30:00+0000")
    push()
    M.check_deploy_drift({"commit": "2553e6d" + "a" * 33, "built_at": "2026-07-30T13:43:34Z"},
                         str(work), rep)
    row = next(r for r in rep.rows if r[1] == "production is current")
    assert row[0] == "FAIL"
    assert "does not exist" in row[2]


def test_production_running_unmerged_code_fails(tmp_path, rep):
    """Ahead of main is not 'current'. It means an image was built from something nobody
    reviewed — the inverse of drift and just as worth knowing."""
    work, commit, push = _repo(tmp_path)
    commit("on main", "2026-07-30T13:30:00+0000")
    push()
    unmerged = commit("never merged", "2026-07-30T15:00:00+0000")
    M.check_deploy_drift({"commit": unmerged, "built_at": "2026-07-30T15:01:00Z"}, str(work), rep)
    row = next(r for r in rep.rows if r[1] == "production is current")
    assert row[0] == "FAIL"
    assert "AHEAD of main" in row[2]


def test_an_unstamped_image_with_no_drift_skips_rather_than_failing(tmp_path, rep):
    """THE ALERT-FATIGUE GUARD, and it is load-bearing.

    Every image built before BUILD_SHA existed lacks a commit. If that alone went red, this
    workflow would be red on every run until the next deploy — which is exactly the state it was
    found in (43 consecutive failures, none of them read by anyone). An unverifiable answer is a
    loud skip; only a POSITIVE finding of drift is a failure.
    """
    work, commit, push = _repo(tmp_path)
    commit("only commit", "2026-07-30T13:30:00+0000")
    push()
    M.check_deploy_drift({"built_at": "2026-07-30T14:00:00Z"}, str(work), rep)
    assert rep.failed == 0
    assert rep.skipped == 1
    assert any("UNVERIFIED" in r[2] for r in rep.rows)
