"""Provisioning must never switch production onto a lane it has not proved.

gpu_up.sh moves the vision lane in-tenant: Ollama on an ACA GPU workload profile, internal
ingress, in acp-app's own environment. "Azure only" means ACP_VISION_PROVIDER=ollama, and
ai.py:616 skips the fallback when the provider IS the floor:

    if not res.get("ok") and getattr(prov, "name", "") != "ollama":

So there is nothing below it. An endpoint that starts but cannot generate turns every 1.1.1
remediation into a silent defer — no error, no alt text, findings that look considered. That is
why the switch-over is gated on a real generation rather than on `Running`, and it is the
property most of these cases exist to hold.

Same harness as tests/test_set_integration_env.py: the real script against a stubbed `az` that
logs every argv. Nothing reaches Azure.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "deploy" / "public" / "gpu_up.sh"

requires_bash = pytest.mark.skipif(
    not shutil.which("bash") or not SCRIPT.exists(), reason="needs bash and the script")

INTERNAL_FQDN = "acp-ollama.internal.greenwater-4bf2c997.eastus2.azurecontainerapps.io"
EXTERNAL_FQDN = "acp-ollama.greenwater-4bf2c997.eastus2.azurecontainerapps.io"


def _stub_az(tmp_path, log: Path, *, fqdn: str = INTERNAL_FQDN,
             generates: bool = True, pulls: bool = True) -> Path:
    """An `az` that answers every probe gpu_up.sh makes, and can fail the two that gate the switch.

    `generates` controls what the verification exec returns; `pulls` controls the model pull.
    Everything else succeeds, so a test that fails tells you about the gate rather than the setup.
    """
    binn = tmp_path / "bin"
    binn.mkdir(exist_ok=True)
    az = binn / "az"
    az.write_text(f"""#!/usr/bin/env bash
printf '%s\\n' "$*" >> {log}

if [ "$1" = account ]; then echo 00000000-0000-0000-0000-000000000000; exit 0; fi

if [ "$1" = containerapp ]; then
  case "$2 $3" in
    "env workload-profile")
      # already present, so the add branch is not the thing under test here
      case "$4" in list) echo "NC8as-T4"; exit 0 ;; esac
      exit 0 ;;
    "exec ") : ;;
  esac
  case "$2" in
    show)
      case "$*" in
        *environmentId*) echo "/subscriptions/x/managedEnvironments/acp-env"; exit 0 ;;
        *ingress.fqdn*)  echo "{fqdn}"; exit 0 ;;
      esac
      exit 0 ;;                       # existence probes
    exec)
      case "$*" in
        *"ollama pull"*) [ "{int(pulls)}" = 1 ] && exit 0 || {{ echo "pull failed" >&2; exit 1; }} ;;
        *api/generate*)  [ "{int(generates)}" = 1 ] && echo "ok" || echo "connection refused"; exit 0 ;;
      esac
      exit 0 ;;
    create|update|secret) exit 0 ;;
  esac
  exit 0
fi
exit 0
""")
    az.chmod(0o755)
    return binn


def _run(tmp_path, binn: Path, **env_extra) -> subprocess.CompletedProcess:
    env = dict(os.environ, PATH=f"{binn}:{os.environ['PATH']}")
    for v in ("ACP_RG", "ACP_APP", "ACP_WORKER", "ACP_GPU_APP", "ACP_ACA_ENV", "ACP_SUBSCRIPTION",
              "ACP_GPU_ACTIVATE", "ACP_GPU_DRY_RUN", "ACP_GPU_RETIRE_RUNPOD",
              "ACP_GPU_PROFILE", "ACP_GPU_VISION_MODEL"):
        env.pop(v, None)
    env.update(env_extra)
    return subprocess.run(["bash", str(SCRIPT)], capture_output=True, text=True,
                          env=env, cwd=str(REPO), stdin=subprocess.DEVNULL, timeout=120)


def _lines(log: Path) -> list[str]:
    return log.read_text().splitlines() if log.exists() else []


def _switches(log: Path) -> list[str]:
    """The calls that repoint production at a provider — the ones that must not happen early."""
    return [ln for ln in _lines(log) if "ACP_VISION_PROVIDER=ollama" in ln]


@requires_bash
def test_it_does_not_switch_over_when_the_endpoint_cannot_generate(tmp_path):
    """The load-bearing case. `Running` is not evidence; a generation is."""
    log = tmp_path / "calls.log"
    r = _run(tmp_path, _stub_az(tmp_path, log, generates=False), ACP_GPU_ACTIVATE="1")
    assert r.returncode != 0, "a non-generating endpoint was accepted"
    assert _switches(log) == [], "production was repointed at an endpoint that cannot generate"
    assert "NOT switching over" in r.stderr


@requires_bash
def test_it_does_not_switch_over_when_the_model_pull_fails(tmp_path):
    log = tmp_path / "calls.log"
    r = _run(tmp_path, _stub_az(tmp_path, log, pulls=False), ACP_GPU_ACTIVATE="1")
    assert r.returncode != 0
    assert _switches(log) == [], "production was repointed at an endpoint with no model"


@requires_bash
def test_external_ingress_is_refused(tmp_path):
    """zone_for_url() would label it 'cloud', and the provenance chip would be telling the truth.

    External ingress is reachable from the internet, so a reviewer reading "the document never
    left your network" would be reading something false. The whole reason to move off a
    third-party GPU is that claim, so the script must not produce a deployment that breaks it.
    """
    log = tmp_path / "calls.log"
    r = _run(tmp_path, _stub_az(tmp_path, log, fqdn=EXTERNAL_FQDN), ACP_GPU_ACTIVATE="1")
    assert r.returncode != 0
    assert _switches(log) == []
    assert "not internal" in r.stderr


@requires_bash
def test_a_verified_endpoint_switches_both_app_and_worker(tmp_path):
    # Remediation runs in the WORKER (ADR 0013 §2). Switching the app alone leaves every real
    # fix on the old provider while the preflight — which runs in the app — reports success.
    log = tmp_path / "calls.log"
    r = _run(tmp_path, _stub_az(tmp_path, log), ACP_GPU_ACTIVATE="1")
    assert r.returncode == 0, r.stdout + r.stderr
    switched = " ".join(_switches(log))
    assert "-n acp-app " in switched + " ", "acp-app was not switched"
    assert "-n acp-worker " in switched + " ", "acp-worker was not switched"
    assert INTERNAL_FQDN in switched, "the new endpoint was not passed as OLLAMA_BASE_URL"


@requires_bash
def test_provisioning_alone_never_switches(tmp_path):
    """Provisioning and cutting production over are different decisions."""
    log = tmp_path / "calls.log"
    r = _run(tmp_path, _stub_az(tmp_path, log))          # no ACP_GPU_ACTIVATE
    assert r.returncode == 0, r.stdout + r.stderr
    assert _switches(log) == [], "provisioning switched production without being asked"
    assert "NOT yet switched over" in r.stdout


@requires_bash
def test_dry_run_changes_nothing(tmp_path):
    log = tmp_path / "calls.log"
    r = _run(tmp_path, _stub_az(tmp_path, log), ACP_GPU_ACTIVATE="1", ACP_GPU_DRY_RUN="1")
    assert r.returncode == 0, r.stdout + r.stderr
    writes = [ln for ln in _lines(log)
              if ln.startswith(("containerapp create", "containerapp update", "containerapp secret"))]
    assert writes == [], f"a dry run wrote to Azure: {writes}"


@requires_bash
def test_retiring_runpod_removes_the_reference_before_the_secret(tmp_path):
    """Order is load-bearing: a dangling secretref crash-loops the next revision.

    RUNPOD_API_KEY is an env var POINTING at the secret. Delete the secret first and the app
    cannot start — ContainerAppSecretRefNotFound, which surfaces as a broken deployment rather
    than as anything about configuration.
    """
    log = tmp_path / "calls.log"
    r = _run(tmp_path, _stub_az(tmp_path, log), ACP_GPU_ACTIVATE="1", ACP_GPU_RETIRE_RUNPOD="1")
    assert r.returncode == 0, r.stdout + r.stderr

    lines = _lines(log)
    rm_var = next((i for i, ln in enumerate(lines) if "--remove-env-vars" in ln), None)
    rm_sec = next((i for i, ln in enumerate(lines) if "secret remove" in ln), None)
    assert rm_var is not None, "the RunPod env vars were never removed"
    assert rm_sec is not None, "the RunPod secret was never removed"
    assert rm_var < rm_sec, "the secret was removed before the env var referencing it"


@requires_bash
def test_retiring_runpod_is_refused_while_it_is_still_serving(tmp_path):
    """Stripping the lane that is currently doing the work is not a cleanup, it is an outage."""
    log = tmp_path / "calls.log"
    r = _run(tmp_path, _stub_az(tmp_path, log), ACP_GPU_RETIRE_RUNPOD="1")   # no ACTIVATE
    assert r.returncode != 0
    assert not [ln for ln in _lines(log) if "--remove-env-vars" in ln or "secret remove" in ln]
    assert "Switch over first" in r.stderr
