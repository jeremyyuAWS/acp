"""The OCR install has to survive the mirror failure that actually happened.

WHAT HAPPENED, and how it was pinned down. On 2026-08-19 the tesseract install failed on
roughly half of all runners for over an hour, and both halves of
`apt-get update -qq && apt-get install -qq` were quiet, so the logs never said which failed.
The timings did: every failed step took 5m30s, and the retry warnings landed 100s and 110s
apart against 10s/20s/30s backoff — so each attempt burned exactly 90s, the `timeout 90` on
`apt-get update`. 3x90 + 60 = 330s = 5m30s.

`apt-get update` was timing out and `apt-get install` NEVER RAN. That is the fact the ladder in
scripts/install_tesseract.sh is built around, and it is what makes rung 1 — install from the
index already on the image, with no update at all — the highest-value rung rather than a
micro-optimisation. Refreshing the index pulls Packages files for every configured source;
installing tesseract-ocr pulls a few .debs. A mirror too congested for the former can usually
still serve the latter.

Each case below drives the REAL script with a stub `apt-get` on PATH, so nothing touches a
network and the rungs can be forced individually. The properties are chosen because each can be
undone by an edit that looks like a simplification:

  · collapse rung 1 into rung 2      -> back to paying for the metadata fetch that was failing
  · drop the fallback mirror         -> a single bad mirror is still terminal
  · let a rung's failure end it      -> a wrong guess about which rung works becomes fatal
  · swallow apt's output again       -> the next outage needs arithmetic to diagnose
  · drop the deadline                -> a hung mirror burns a runner instead of failing

NOT a test that OCR loss is tolerable. Failure still exits non-zero; ci.yml's gate and
test_ocr_criteria_are_covered_in_ci still fail the build. This only tests that we try hard
before getting there.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "install_tesseract.sh"

requires_bash = pytest.mark.skipif(
    not shutil.which("bash") or not SCRIPT.exists(), reason="needs bash and the script")


def _stub(tmp_path, log: Path, *, update="fail", install="fail",
          install_needs_update=False, fallback_update="ok", with_tesseract=False) -> Path:
    """A fake apt-get whose update/install outcomes are set per scenario.

    `install_needs_update` models the real stale-index case: installing fails until an update
    has been run, which is what makes rung 1 fall through to rung 2 rather than succeed.
    `fallback_update` is consulted only when the update names our fallback sources list, so a
    scenario can make the configured mirror hopeless while the fallback works.
    """
    binn = tmp_path / "bin"
    binn.mkdir(exist_ok=True)
    marker = tmp_path / "updated"
    body = f"""#!/usr/bin/env bash
printf '%s\\n' "$*" >> {log}
mode=""
for a in "$@"; do
  case "$a" in
    update)  mode=update;  break ;;
    install) mode=install; break ;;
  esac
done
if [ "$mode" = update ]; then
  if printf '%s' "$*" | grep -q 'acp-fallback-list'; then
    if [ "{fallback_update}" = ok ]; then touch {marker}; echo "Reading package lists"; exit 0; fi
    echo "E: fallback mirror unreachable" >&2; exit 1
  fi
  if [ "{update}" = ok ]; then touch {marker}; echo "Reading package lists"; exit 0; fi
  echo "E: Failed to fetch http://azure.archive.ubuntu.com/ubuntu/dists/noble/InRelease" >&2
  exit 1
fi
if [ "$mode" = install ]; then
  if [ "{str(install_needs_update).lower()}" = true ] && [ ! -f {marker} ]; then
    echo "E: Unable to locate package tesseract-ocr" >&2; exit 100
  fi
  if [ "{install}" = ok ]; then echo "Setting up tesseract-ocr"; exit 0; fi
  echo "E: Failed to fetch .../tesseract-ocr_5.deb" >&2; exit 100
fi
exit 0
"""
    apt = binn / "apt-get"
    apt.write_text(body)
    apt.chmod(0o755)
    if with_tesseract:
        t = binn / "tesseract"
        t.write_text("#!/usr/bin/env bash\necho 'tesseract 5.3.0'\n")
        t.chmod(0o755)
    return binn


def _run(tmp_path, binn: Path, **env_extra) -> subprocess.CompletedProcess:
    # PATH keeps /usr/bin and /bin because the script needs timeout, mktemp, sleep and grep.
    # That also means a REAL tesseract on PATH is visible to rung 0 — and on CI there always is
    # one, because the workflow installs it before the suite runs. Shadowing cannot help: an
    # earlier PATH entry can add a binary, never hide one. So rung 0 is pointed at a name that
    # cannot exist, and the rung-0 test overrides it back.
    #
    # This is the bug CI caught on cecaa9b: without it every case below exited 0 at
    # "tesseract already present" having exercised nothing, green locally and red on CI.
    env = dict(os.environ, PATH="{}:/usr/bin:/bin".format(binn))
    env["ACP_TESSERACT_PROBE"] = "acp-tesseract-probe-that-cannot-exist"
    env["ACP_SUDO"] = ""                     # no sudo in the test environment
    env["ACP_APT_BACKOFF"] = "0"             # the real 5s/10s backoff is not worth the wall clock
    env["ACP_APT_CODENAME"] = "noble"        # don't depend on this container's /etc/os-release
    env["ACP_APT_FALLBACK_LIST"] = str(tmp_path / "acp-fallback-list")
    env.setdefault("ACP_TESSERACT_DEADLINE", "60")
    env.update(env_extra)
    return subprocess.run(["bash", str(SCRIPT)], capture_output=True, text=True,
                          env=env, cwd=str(REPO), stdin=subprocess.DEVNULL, timeout=180)


def _calls(log: Path) -> list[str]:
    return log.read_text().splitlines() if log.exists() else []


def _updates(log: Path) -> list[str]:
    return [c for c in _calls(log) if " update" in " {} ".format(c)]


@requires_bash
def test_the_fast_path_installs_without_ever_refreshing_the_index(tmp_path):
    """THE load-bearing case: we must not pay for the operation that was failing.

    `apt-get update` is what timed out on 2026-08-19, three times per job, while install never
    ran at all. If this ever calls update on the happy path, the fix has been undone.
    """
    log = tmp_path / "calls.log"
    binn = _stub(tmp_path, log, install="ok")
    r = _run(tmp_path, binn)
    assert r.returncode == 0, r.stdout + r.stderr
    assert _updates(log) == [], \
        "the fast path ran apt-get update — the exact call that was timing out: {}".format(_calls(log))
    assert any("install" in c for c in _calls(log))


@requires_bash
def test_an_already_present_tesseract_costs_nothing(tmp_path):
    # The one case that WANTS rung 0 to fire, so it puts the probe back to the real name.
    log = tmp_path / "calls.log"
    binn = _stub(tmp_path, log, with_tesseract=True)
    r = _run(tmp_path, binn, ACP_TESSERACT_PROBE="tesseract")
    assert r.returncode == 0, r.stdout + r.stderr
    assert _calls(log) == [], "apt was invoked although tesseract was already installed"


@requires_bash
def test_a_stale_index_falls_through_to_update_rather_than_failing(tmp_path):
    """Rung 1 is an optimisation, not a gamble — its failure must cost only time."""
    log = tmp_path / "calls.log"
    binn = _stub(tmp_path, log, update="ok", install="ok", install_needs_update=True)
    r = _run(tmp_path, binn)
    assert r.returncode == 0, r.stdout + r.stderr
    assert _updates(log), "never refreshed the index, so a stale image could never install"


@requires_bash
def test_a_dead_configured_mirror_is_survived_by_the_fallback(tmp_path):
    """One bad mirror must not be terminal — that is the whole outage, reproduced."""
    log = tmp_path / "calls.log"
    binn = _stub(tmp_path, log, update="fail", fallback_update="ok",
                 install="ok", install_needs_update=True)
    r = _run(tmp_path, binn)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (tmp_path / "acp-fallback-list").exists(), "no fallback sources list was written"
    assert any("acp-fallback-list" in c for c in _calls(log)), \
        "the fallback list was written but never used for an update"


@requires_bash
def test_the_fallback_update_does_not_re_contact_the_slow_mirror(tmp_path):
    """Restricting sourcelist is the point: re-reading the mirror we just proved slow wastes
    the remaining budget on the thing that already failed."""
    log = tmp_path / "calls.log"
    binn = _stub(tmp_path, log, update="fail", fallback_update="ok",
                 install="ok", install_needs_update=True)
    r = _run(tmp_path, binn)
    assert r.returncode == 0, r.stdout + r.stderr
    fb = [c for c in _updates(log) if "acp-fallback-list" in c]
    assert fb, "no fallback update was issued"
    for c in fb:
        assert "Dir::Etc::sourceparts=/dev/null" in c, \
            "the fallback update still reads the other sources: {}".format(c)


@requires_bash
def test_total_failure_exits_nonzero_and_names_the_cause(tmp_path):
    """OCR loss stays fatal. The gate depends on this exit code."""
    log = tmp_path / "calls.log"
    binn = _stub(tmp_path, log, update="fail", fallback_update="fail", install="fail")
    r = _run(tmp_path, binn)
    assert r.returncode != 0, "a total mirror failure reported success"
    assert "::error::" in r.stdout
    assert "1.4.5" in r.stdout, "the message does not say which criteria are lost"


@requires_bash
def test_apt_output_is_surfaced_rather_than_swallowed(tmp_path):
    """`-qq` on both halves is why today's diagnosis needed timing arithmetic."""
    log = tmp_path / "calls.log"
    binn = _stub(tmp_path, log, update="fail", fallback_update="fail", install="fail")
    r = _run(tmp_path, binn)
    assert "Failed to fetch" in r.stdout, \
        "apt's own error text never reached the log, so the next outage is undiagnosable"


@requires_bash
def test_it_gives_up_at_the_deadline_instead_of_burning_the_runner(tmp_path):
    """A hung mirror must cost a bounded amount of runner time."""
    log = tmp_path / "calls.log"
    binn = _stub(tmp_path, log, update="fail", fallback_update="fail", install="fail")
    r = _run(tmp_path, binn, ACP_TESSERACT_DEADLINE="1")
    assert r.returncode != 0
    assert "::error::" in r.stdout


# ── both pipelines must actually use it ───────────────────────────────────────────────────────
# The script is only worth having if nothing bypasses it. azure-pipelines.yml held the LAST
# unhardened copy — `apt-get update -qq && apt-get install -qq`, no timeout, no retry, no
# fallback — so the pipeline least likely to be watched carried the most fragile version.

CI = REPO / ".github" / "workflows" / "ci.yml"
ADO = REPO / "azure-pipelines.yml"


@pytest.mark.skipif(not CI.exists(), reason="needs ci.yml")
def test_github_actions_installs_via_the_script():
    assert "scripts/install_tesseract.sh" in CI.read_text(), \
        "ci.yml no longer calls the install script"


@pytest.mark.skipif(not ADO.exists(), reason="needs azure-pipelines.yml")
def test_azure_pipelines_installs_via_the_script():
    assert "scripts/install_tesseract.sh" in ADO.read_text(), \
        "azure-pipelines.yml no longer calls the install script"


@pytest.mark.skipif(not ADO.exists(), reason="needs azure-pipelines.yml")
def test_no_pipeline_still_shells_out_to_a_bare_apt_install():
    """A re-inlined one-liner would look like a simplification and quietly undo all of this."""
    import re
    for f in (p for p in (CI, ADO) if p.exists()):
        for line in f.read_text().splitlines():
            if "install_tesseract.sh" in line or line.lstrip().startswith("#"):
                continue
            assert not re.search(r"apt-get\s+install.*tesseract", line), \
                "{} installs tesseract directly, bypassing the script: {!r}".format(f.name, line.strip())
