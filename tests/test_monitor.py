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


# ── deploy drift: only commits that could change the image ────────────────────────────
#
# The drift check counted ANY commit newer than the build, by timestamp. In a repo landing ~20
# PRs a day that meant a docs-only PR turned the monitor red about a production that was
# perfectly current — and a check that is usually red is one people learn to skip, which is how
# the four-hour drift it exists to catch went unnoticed in the first place.
#
# These tests pin both halves: a shipping commit must still fail, and — the half that is easy to
# get wrong — anything we cannot prove is cosmetic must still fail.

def _git_log(*blocks):
    """Fake `git log -m --first-parent --name-only --format=%x00%h %s` output.

    The blank line after the subject is NOT decoration — it is what real git emits, verified
    against this repo's own history. A fixture that omitted it would still pass (the parser drops
    empty lines) while proving nothing about the format the check actually meets in production.
    """
    return "".join("\x00" + subject + "\n\n" + "".join(p + "\n" for p in paths)
                   for subject, paths in blocks)


def _drift(monkeypatch, rep, log, built="2026-07-30T12:00:00Z"):
    def fake_run(cmd, **kw):
        class R: stdout = "" if "fetch" in cmd else log
        return R()
    monkeypatch.setattr(M.subprocess, "run", fake_run)
    M.check_deploy_drift({"built_at": built}, ".", rep)


def test_a_docs_only_commit_does_not_report_drift(monkeypatch, rep):
    _drift(monkeypatch, rep, _git_log(("abc123 docs: tidy", ["docs/pipeline.md", "README.md"])))
    assert rep.failed == 0
    assert any("nothing that ships has merged" in r[2] for r in rep.rows)


def test_a_tests_only_commit_does_not_report_drift(monkeypatch, rep):
    _drift(monkeypatch, rep, _git_log(("abc123 test: more cases", ["tests/test_scanner.py"])))
    assert rep.failed == 0


def test_a_ci_workflow_change_does_not_report_drift(monkeypatch, rep):
    _drift(monkeypatch, rep, _git_log(("abc123 ci: bump", [".github/workflows/ci.yml"])))
    assert rep.failed == 0


def test_the_root_level_azure_pipelines_ci_file_does_not_report_drift(monkeypatch, rep):
    """It lives at the repo root, so `.github/` never reaches it and `.yml` is not a root
    suffix exempt — yet no COPY ships it. Before it was exempted by name, #235's `d9b5f14`
    (which touched only this file) turned the monitor red naming a CI change as production drift."""
    _drift(monkeypatch, rep, _git_log(("d9b5f14 ci(azure): retire triggers", ["azure-pipelines.yml"])))
    assert rep.failed == 0
    assert any("nothing that ships has merged" in r[2] for r in rep.rows)
    assert M._touches_image(["azure-pipelines.yml"]) is False


def test_the_deploy_script_does_not_ship_but_the_dockerfile_does(monkeypatch, rep):
    """redeploy.sh runs from a laptop; the Dockerfile IS the image. Same directory, opposite
    answers — which is why the exemption is by filename, not by `deploy/`."""
    _drift(monkeypatch, rep, _git_log(("a1 fix(deploy): pin", ["deploy/public/redeploy.sh"])))
    assert rep.failed == 0
    rep2 = M.Report()
    _drift(monkeypatch, rep2, _git_log(("a2 fix: base image", ["deploy/public/Dockerfile"])))
    assert rep2.failed == 1


def test_an_api_change_still_reports_drift(monkeypatch, rep):
    """The check must not have been softened into uselessness."""
    _drift(monkeypatch, rep, _git_log(("abc123 fix(scan): real fix", ["api/scanner.py"])))
    assert rep.failed == 1
    assert any("change what production runs" in r[2] for r in rep.rows)


def test_a_mixed_commit_counts_as_shipping(monkeypatch, rep):
    """One shipped file is enough. A commit is not cosmetic because most of it was."""
    _drift(monkeypatch, rep, _git_log(("a1 fix + docs", ["docs/x.md", "api/store.py"])))
    assert rep.failed == 1


def test_cosmetic_commits_are_still_reported_alongside_a_real_one(monkeypatch, rep):
    _drift(monkeypatch, rep, _git_log(("a1 fix", ["api/x.py"]), ("a2 docs", ["docs/y.md"])))
    assert rep.failed == 1
    assert any("1 docs/test-only commit(s) ignored" in r[2] for r in rep.rows)


def test_cosmetic_commits_are_reported_on_a_GREEN_run_too(monkeypatch, rep):
    """'Nothing merged' and 'nothing shipped' are different facts. A reader must not have to
    guess which one a green run is telling them."""
    _drift(monkeypatch, rep, _git_log(("a2 docs", ["docs/y.md"])))
    assert rep.failed == 0
    assert any("1 docs/test-only commit(s) ignored" in r[2] for r in rep.rows)


# ── the fail-safe direction ───────────────────────────────────────────────────────────

def test_an_unknown_path_counts_as_shipping(monkeypatch, rep):
    """The exemption list is a DENYLIST on purpose. A directory nobody has classified must fail
    the check, not pass it — a false GREEN here is the monitor going quiet about an undeployed
    change, which is the exact failure this file exists to prevent."""
    _drift(monkeypatch, rep, _git_log(("a1 feat: new thing", ["brand_new_dir/thing.py"])))
    assert rep.failed == 1


def test_a_commit_with_no_listed_paths_counts_as_shipping(monkeypatch, rep):
    """git told us nothing — an empty tree, a merge, a format we did not anticipate. The honest
    answer is 'assume it matters', never 'assume it is fine'."""
    assert M._touches_image([]) is True


def test_a_markdown_file_inside_a_shipping_directory_is_not_exempt(monkeypatch, rep):
    """The .md exemption is root-level only. config/ and hub/ are copied into the image, so a
    markdown file there could genuinely be read at runtime."""
    assert M._touches_image(["hub/index.md"]) is True
    assert M._touches_image(["README.md"]) is False


def test_no_commits_at_all_is_green(monkeypatch, rep):
    _drift(monkeypatch, rep, "")
    assert rep.failed == 0
    assert any("nothing that ships has merged" in r[2] for r in rep.rows)


def test_git_failure_skips_rather_than_passing(monkeypatch, rep):
    def boom(cmd, **kw):
        raise OSError("git missing")
    monkeypatch.setattr(M.subprocess, "run", boom)
    M.check_deploy_drift({"built_at": "2026-07-30T12:00:00Z"}, ".", rep)
    assert rep.failed == 0 and rep.skipped == 1


def test_a_missing_built_at_skips_rather_than_passing(rep):
    M.check_deploy_drift({}, ".", rep)
    assert rep.failed == 0 and rep.skipped == 1


def test_the_parser_matches_what_real_git_actually_prints():
    """The fixtures above are hand-built. This one runs the real command against this repo, so a
    git format change breaks a test instead of silently making every commit look cosmetic —
    which would be a false GREEN, the failure mode this check must never have.
    """
    import subprocess as _sp
    repo = str(Path(__file__).resolve().parent.parent)
    out = _sp.run(["git", "-C", repo, "log", "-m", "--first-parent", "--name-only",
                   "--format=%x00%h %s", "-20", "origin/main"],
                  capture_output=True, text=True, timeout=60)
    if out.returncode != 0 or not out.stdout.strip():
        pytest.skip("no origin/main in this checkout")
    blocks = [b for b in out.stdout.split("\x00") if b.strip()]
    assert blocks, "the NUL record separator did not split the log"
    for block in blocks:
        lines = [l for l in block.splitlines() if l.strip()]
        subject, paths = lines[0], lines[1:]
        # Every commit in this repo touches at least one file, and none of the paths may be the
        # subject line leaking through — the bug a format change would actually cause.
        assert paths, f"no paths parsed for {subject!r}"
        assert not any(p.startswith(subject[:8]) for p in paths)
    # And the classifier returns a real bool for every one of them.
    assert all(isinstance(M._touches_image([l for l in b.splitlines() if l.strip()][1:]), bool)
               for b in blocks)


def test_the_local_compose_stack_is_not_the_production_image(monkeypatch, rep):
    """deploy/compose/ runs the stack on a laptop. Nothing COPYs it, so a change there cannot
    reach production — but deploy/public/Dockerfile in the SAME commit can, which is why the two
    are classified independently rather than by their shared parent directory."""
    _drift(monkeypatch, rep, _git_log(("a1 fix(compose): local worker",
                                       ["deploy/compose/docker-compose.yml"])))
    assert rep.failed == 0
    rep2 = M.Report()
    _drift(monkeypatch, rep2, _git_log(("a2 fix(image): fixtures",
                                        ["deploy/compose/README.md", "deploy/public/Dockerfile"])))
    assert rep2.failed == 1
