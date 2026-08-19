"""The app and the worker must move together, and the secret must never reach argv.

set_integration_env.sh exists because `az containerapp update` is easy to run on acp-app and
forget on acp-worker. Scanning happens in the WORKER (ADR 0013 §2 — the API runs ACP_WORKERS=0
and serves only), so Langfuse configured on acp-app alone yields traces for the API and none for
Discover. That reads as "tracing is broken", not as "tracing is half-configured", and it is the
same silent-and-reassuring failure the preflight was written against.

These run the REAL script with a stubbed `az` on PATH and assert on what the script tried to do.
Nothing reaches Azure. Same shape as tests/test_redeploy_pin_resolution.py, which stubs `az`/`gh`
and lets redeploy.sh die at the point of interest.

The stub records every argv it is handed, one call per line. That is what makes the pairing
assertion possible at all: "did BOTH apps get this var" is a question about the calls, and no
amount of reading the script proves the loop covers the list it is given.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "deploy" / "public" / "set_integration_env.sh"

requires_bash = pytest.mark.skipif(
    not shutil.which("bash") or not SCRIPT.exists(), reason="needs bash and the script")

FAKE_SK = "sk-lf-0000000000000000000000000000000000"
FAKE_PK = "pk-lf-1111111111111111111111111111111111"
FAKE_CID = "11111111-2222-3333-4444-555555555555"
FAKE_TID = "66666666-7777-8888-9999-000000000000"


def _stub_az(tmp_path, log: Path, *, worker_exists: bool = True, fail_on: str = "") -> Path:
    """An `az` that answers the probes, logs every call, and can be made to fail on one app.

    `fail_on` names a container app whose WRITE calls (secret set / update) exit non-zero, so a
    test can ask what the script does when the pair cannot be kept in step.
    """
    binn = tmp_path / "bin"
    binn.mkdir(exist_ok=True)
    az = binn / "az"
    az.write_text(f"""#!/usr/bin/env bash
printf '%s\\n' "$*" >> {log}

# subscription probe
if [ "$1" = account ]; then echo 00000000-0000-0000-0000-000000000000; exit 0; fi

if [ "$1" = containerapp ]; then
  # which app is this call about?
  APPNAME=""; PREV=""
  for a in "$@"; do
    if [ "$PREV" = "-n" ]; then APPNAME="$a"; fi
    PREV="$a"
  done

  case "$2" in
    show)
      # A `show` carrying --query is the read-back; one without is the existence probe.
      case "$*" in
        *--query*) echo ""; exit 0 ;;
      esac
      if [ "$APPNAME" = "acp-worker" ] && [ "{int(worker_exists)}" = "0" ]; then exit 1; fi
      exit 0
      ;;
    secret|update)
      if [ -n "{fail_on}" ] && [ "$APPNAME" = "{fail_on}" ]; then
        echo "stubbed failure (BadRequest)" >&2; exit 1
      fi
      exit 0
      ;;
  esac
  exit 0
fi
exit 0
""")
    az.chmod(0o755)
    return binn


def _run(tmp_path, binn: Path, **env_extra) -> subprocess.CompletedProcess:
    env = dict(os.environ, PATH=f"{binn}:{os.environ['PATH']}")
    # Never inherit the developer's real values — a machine that happens to have LANGFUSE_HOST
    # exported would silently change what these assert.
    for v in ("LANGFUSE_HOST", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY",
              "ACP_AZURE_CLIENT_ID", "ACP_AZURE_TENANT_ID", "ACP_SUBSCRIPTION",
              "ACP_RG", "ACP_APP", "ACP_WORKER", "ACP_SET_ENV_DRY_RUN"):
        env.pop(v, None)
    env.update(env_extra)
    return subprocess.run(["bash", str(SCRIPT)], capture_output=True, text=True,
                          env=env, cwd=str(REPO), stdin=subprocess.DEVNULL, timeout=120)


def _writes(log: Path) -> list[str]:
    """The calls that CHANGE something — existence probes and read-backs are not interesting."""
    if not log.exists():
        return []
    return [ln for ln in log.read_text().splitlines()
            if ln.startswith("containerapp secret") or ln.startswith("containerapp update")]


def _for_app(log: Path, app: str) -> list[str]:
    return [ln for ln in _writes(log) if f"-n {app} " in ln + " "]


@requires_bash
def test_langfuse_lands_on_both_app_and_worker(tmp_path):
    log = tmp_path / "calls.log"
    r = _run(tmp_path, _stub_az(tmp_path, log), LANGFUSE_SECRET_KEY=FAKE_SK)
    assert r.returncode == 0, r.stdout + r.stderr

    for app in ("acp-app", "acp-worker"):
        calls = " ".join(_for_app(log, app))
        assert "secret set" in calls, f"{app} never had its Langfuse secrets set"
        assert "LANGFUSE_SECRET_KEY=secretref:langfuse-sk" in calls, \
            f"{app} never had LANGFUSE_SECRET_KEY wired to the secret"
        assert "LANGFUSE_HOST=" in calls, f"{app} never had LANGFUSE_HOST set"


@requires_bash
def test_sharepoint_lands_on_both_app_and_worker(tmp_path):
    # The worker needs it too: it is the tier that opens files, so a Graph token it cannot
    # resolve an authority for fails there and nowhere the operator is looking.
    log = tmp_path / "calls.log"
    r = _run(tmp_path, _stub_az(tmp_path, log),
             ACP_AZURE_CLIENT_ID=FAKE_CID, ACP_AZURE_TENANT_ID=FAKE_TID)
    assert r.returncode == 0, r.stdout + r.stderr

    for app in ("acp-app", "acp-worker"):
        calls = " ".join(_for_app(log, app))
        assert f"ACP_AZURE_CLIENT_ID={FAKE_CID}" in calls, f"{app} missing the client id"
        assert f"ACP_AZURE_TENANT_ID={FAKE_TID}" in calls, f"{app} missing the tenant id"


@requires_bash
def test_the_secret_value_never_appears_in_an_env_var_argument(tmp_path):
    """It goes in via `secret set` and is referenced by name — never inlined as an env value.

    An env var carrying the literal is readable by anyone with `containerapp show` on the app,
    which is a strictly wider audience than the secret store's.
    """
    log = tmp_path / "calls.log"
    r = _run(tmp_path, _stub_az(tmp_path, log), LANGFUSE_SECRET_KEY=FAKE_SK)
    assert r.returncode == 0, r.stdout + r.stderr

    updates = [ln for ln in _writes(log) if ln.startswith("containerapp update")]
    assert updates, "nothing was updated — the assertion below would pass vacuously"
    for ln in updates:
        assert FAKE_SK not in ln, f"the secret key was passed as an env-var value: {ln}"
    # And it must not be echoed to the operator's terminal either.
    assert FAKE_SK not in r.stdout and FAKE_SK not in r.stderr


@requires_bash
def test_a_group_with_no_inputs_is_skipped_and_says_so(tmp_path):
    log = tmp_path / "calls.log"
    r = _run(tmp_path, _stub_az(tmp_path, log), ACP_AZURE_CLIENT_ID=FAKE_CID)
    assert r.returncode == 0, r.stdout + r.stderr

    assert not [ln for ln in _writes(log) if "secret set" in ln], \
        "Langfuse secrets were set despite no LANGFUSE_SECRET_KEY"
    assert "Langfuse SKIPPED" in r.stdout, "a skipped group must say it was skipped"
    # The SharePoint half still ran — the groups are independent.
    assert [ln for ln in _writes(log) if "ACP_AZURE_CLIENT_ID" in ln]


@requires_bash
def test_a_malformed_secret_key_is_refused_before_anything_is_written(tmp_path):
    """The guard has to fire BEFORE the first write, or it only protects the second app."""
    log = tmp_path / "calls.log"
    r = _run(tmp_path, _stub_az(tmp_path, log), LANGFUSE_SECRET_KEY="hunter2")
    assert r.returncode != 0
    assert _writes(log) == [], "a write happened despite the key being rejected"


@requires_bash
def test_a_worker_that_cannot_be_updated_fails_the_run(tmp_path):
    """Half-applied is the state this script exists to prevent, so it must not exit 0.

    It cannot be prevented outright — the app is written before the worker — but exiting 0 on a
    split pair is what turns it into a silent misconfiguration. The failure must be loud and must
    name the risk.
    """
    log = tmp_path / "calls.log"
    r = _run(tmp_path, _stub_az(tmp_path, log, fail_on="acp-worker"),
             LANGFUSE_SECRET_KEY=FAKE_SK)
    assert r.returncode != 0, "a worker that could not be configured was reported as success"
    assert "acp-worker" in r.stderr


@requires_bash
def test_a_single_tier_deployment_configures_the_app_and_says_there_is_no_worker(tmp_path):
    """"The worker was skipped" and "there is no worker" must not look alike."""
    log = tmp_path / "calls.log"
    r = _run(tmp_path, _stub_az(tmp_path, log, worker_exists=False),
             LANGFUSE_SECRET_KEY=FAKE_SK)
    assert r.returncode == 0, r.stdout + r.stderr
    assert _for_app(log, "acp-app"), "the app was not configured"
    assert not _for_app(log, "acp-worker"), "a non-existent worker was written to"
    assert "single-tier" in r.stdout


@requires_bash
def test_dry_run_changes_nothing(tmp_path):
    log = tmp_path / "calls.log"
    r = _run(tmp_path, _stub_az(tmp_path, log), LANGFUSE_SECRET_KEY=FAKE_SK,
             ACP_AZURE_CLIENT_ID=FAKE_CID, ACP_SET_ENV_DRY_RUN="1")
    assert r.returncode == 0, r.stdout + r.stderr
    assert _writes(log) == [], "a dry run wrote to Azure"
    assert "DRY RUN" in r.stdout
