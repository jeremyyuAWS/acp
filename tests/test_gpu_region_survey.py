"""Where COULD the GPU go — asked of Azure, and answering without changing anything.

East US 2, where mdk-accessibility-env lives, turned out to offer D4/D8/D16/D32, E4–E32,
Consumption and Flex — and no GPU workload profile of any kind. That makes "try another region"
the obvious next thought, so `ACP_GPU_FIND_REGION=1` answers which regions actually have one.

THE CAVEAT THE SURVEY CARRIES, and the reason its output is not a green light: internal ingress
resolves only INSIDE a Container Apps environment, and an environment lives in one region. A GPU
app in another region is a different environment, reachable from acp-app only over EXTERNAL
ingress — which zone_for_url() labels "cloud", making a reviewer's provenance chip say the
document left the network. Truthfully. So the survey informs a decision about moving the whole
environment or reaching a GPU over private networking; it is not a config switch.

Same harness as tests/test_gpu_up.py: the real script against a stubbed `az`. Nothing reaches
Azure. The stub varies its answer BY REGION, which is the whole point — a survey that returns the
same list everywhere would pass a test that proves nothing.
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

Q = '"'


def _stub_regions(tmp_path, log: Path, *, per_region: dict,
                  regions=("eastus2", "westus3")) -> Path:
    binn = tmp_path / "bin"
    binn.mkdir(exist_ok=True)
    cases = "\n".join(
        "        {r}) printf '%s\\n' {skus} ;;".format(
            r=r, skus=" ".join(Q + s + Q for s in skus))
        for r, skus in per_region.items())
    region_list = " ".join(Q + r + Q for r in regions)
    body = """#!/usr/bin/env bash
printf '%s\\n' "$*" >> {log}
if [ "$1" = account ]; then
  case "$2" in
    show)           echo 00000000-0000-0000-0000-000000000000; exit 0 ;;
    list-locations) printf '%s\\n' {region_list}; exit 0 ;;
  esac
  exit 0
fi
if [ "$1" = containerapp ]; then
  if [ "$2 $3" = "env workload-profile" ] && [ "$4" = list-supported ]; then
    PREV=""
    for a in "$@"; do
      if [ "$PREV" = "-l" ]; then REGION="$a"; fi
      PREV="$a"
    done
    case "$REGION" in
{cases}
    esac
    exit 0
  fi
  exit 0
fi
exit 0
""".format(log=log, region_list=region_list, cases=cases)
    az = binn / "az"
    az.write_text(body)
    az.chmod(0o755)
    return binn


def _run(tmp_path, binn: Path, **env_extra) -> subprocess.CompletedProcess:
    env = dict(os.environ, PATH="{}:{}".format(binn, os.environ["PATH"]))
    for v in ("ACP_RG", "ACP_APP", "ACP_WORKER", "ACP_GPU_APP", "ACP_ACA_ENV", "ACP_SUBSCRIPTION",
              "ACP_GPU_ACTIVATE", "ACP_GPU_DRY_RUN", "ACP_GPU_RETIRE_RUNPOD",
              "ACP_GPU_PROFILE", "ACP_GPU_PROFILE_TYPE", "ACP_GPU_VISION_MODEL",
              "ACP_GPU_FIND_REGION", "ACP_GPU_REGIONS"):
        env.pop(v, None)
    env.update(env_extra)
    return subprocess.run(["bash", str(SCRIPT)], capture_output=True, text=True,
                          env=env, cwd=str(REPO), stdin=subprocess.DEVNULL, timeout=120)


def _lines(log: Path) -> list[str]:
    return log.read_text().splitlines() if log.exists() else []


@requires_bash
def test_it_reports_only_regions_that_actually_have_a_gpu(tmp_path):
    log = tmp_path / "calls.log"
    binn = _stub_regions(tmp_path, log, per_region={
        "eastus2": ("D4", "D8", "Consumption", "Flex"),        # the real answer we got back
        "westus3": ("D4", "Consumption", "Consumption-GPU-NC8as-T4"),
    })
    r = _run(tmp_path, binn, ACP_GPU_FIND_REGION="1")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "westus3" in r.stdout
    assert "Consumption-GPU-NC8as-T4" in r.stdout, "the SKU that makes the region useful is not shown"
    assert "✓  eastus2" not in r.stdout, "a region with no GPU was reported as a hit"


@requires_bash
def test_it_provisions_nothing_even_with_activate_set(tmp_path):
    """It is a survey. Creating anything while answering "where could this go" is a bug."""
    log = tmp_path / "calls.log"
    binn = _stub_regions(tmp_path, log, per_region={
        "eastus2": ("D4",), "westus3": ("Consumption-GPU-NC8as-T4",)})
    r = _run(tmp_path, binn, ACP_GPU_FIND_REGION="1", ACP_GPU_ACTIVATE="1")
    assert r.returncode == 0, r.stdout + r.stderr
    writes = [ln for ln in _lines(log)
              if "workload-profile add" in ln
              or ln.startswith(("containerapp create", "containerapp update",
                                "containerapp secret"))]
    assert writes == [], "the survey changed something: {}".format(writes)
    assert not [ln for ln in _lines(log) if "ACP_VISION_PROVIDER" in ln], \
        "the survey repointed production"


@requires_bash
def test_no_gpu_anywhere_reads_as_a_subscription_entitlement_not_a_region_choice(tmp_path):
    """If no region has it, sending someone to go pick a different region wastes their afternoon.

    The distinction is real: a region gap is fixed by moving, an entitlement gap is not.
    """
    log = tmp_path / "calls.log"
    binn = _stub_regions(tmp_path, log, per_region={
        "eastus2": ("D4", "Consumption"), "westus3": ("D4", "Consumption")})
    r = _run(tmp_path, binn, ACP_GPU_FIND_REGION="1")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "subscription-level" in r.stdout
    assert "request GPU quota" in r.stdout


@requires_bash
def test_an_unqueryable_region_is_said_so_rather_than_silently_dropped(tmp_path):
    """"We did not look" and "we looked and there is none" are different facts.

    Blurring them is how an operator ends up requesting quota in a region that never had any.
    """
    log = tmp_path / "calls.log"
    binn = _stub_regions(tmp_path, log,
                         per_region={"westus3": ("Consumption-GPU-NC8as-T4",)},
                         regions=("eastus2", "westus3"))   # eastus2 has no case → empty answer
    r = _run(tmp_path, binn, ACP_GPU_FIND_REGION="1")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "?  eastus2" in r.stdout
    assert "could not query" in r.stdout


@requires_bash
def test_the_output_repeats_the_ingress_caveat_when_it_finds_something(tmp_path):
    """A hit is not a green light — that is the whole risk of answering this question well."""
    log = tmp_path / "calls.log"
    binn = _stub_regions(tmp_path, log, per_region={
        "eastus2": ("D4",), "westus3": ("Consumption-GPU-NC8as-T4",)})
    r = _run(tmp_path, binn, ACP_GPU_FIND_REGION="1")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "internal ingress" in r.stdout
    assert "cloud" in r.stdout
