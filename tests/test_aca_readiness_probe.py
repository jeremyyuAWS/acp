"""scripts/aca_readiness_probe.py — the half of the ACA readiness gate that CAN be tested.

The `az` call in deploy.sh cannot be exercised without a live subscription. The decision it
carries out is pure data: which container gets the probe, which probes survive, and whether
anything needs writing at all. That decision rewrites the production app's template, so it is
tested here rather than trusted.

The failure this guards against is not "the probe is missing". It is the opposite: a patch that
succeeds and drops the image, the environment or somebody else's liveness probe on its way
through, because `az containerapp update --yaml` REPLACES the template it is handed.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
SCRIPT = ACP / "scripts" / "aca_readiness_probe.py"
sys.path.insert(0, str(ACP / "scripts"))

import aca_readiness_probe as mod  # noqa: E402


def _template(**over) -> dict:
    """A template shaped like `az containerapp show --query properties.template` really prints."""
    t = {
        "revisionSuffix": "",
        "containers": [{
            "name": "acp-app",
            "image": "mdkaccessibilityacr.azurecr.io/acp-app:abc1234-1756700000",
            "resources": {"cpu": 1.0, "memory": "2.0Gi"},
            "env": [
                {"name": "ACP_BUILD_VERSION", "value": "2026.9.1.3"},
                {"name": "ACP_DATABASE_URL", "secretRef": "database-url"},
            ],
        }],
        "scale": {"minReplicas": 1, "maxReplicas": 1},
        "volumes": None,
    }
    t.update(over)
    return t


def _run(stdin: str, *args) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), *args], input=stdin,
                          capture_output=True, text=True)


# ── what it writes ────────────────────────────────────────────────────────────────────────
def test_it_adds_a_readiness_probe_pointed_at_the_container_local_endpoint():
    out = mod.patch(_template(), "acp-app")
    probes = out["containers"][0]["probes"]
    assert [p["type"] for p in probes] == ["Readiness"]
    assert probes[0]["httpGet"]["path"] == "/probe/readyz"
    assert probes[0]["httpGet"]["port"] == 8077


def test_it_never_writes_a_liveness_or_startup_probe():
    """A liveness probe on this endpoint would be actively harmful. /probe/readyz answers 503
    when the database is unreachable, and liveness reads 503 as "restart the container" — a
    crash loop that cannot fix a database. Readiness withdraws the replica and restores it by
    itself when the check recovers, which is the behaviour wanted."""
    out = mod.patch(_template(), "acp-app")
    assert {p["type"] for p in out["containers"][0]["probes"]} == {"Readiness"}
    assert "Liveness" not in json.dumps(mod.READINESS_PROBE)


def test_admission_is_fast_and_withdrawal_is_slow():
    """The asymmetry the numbers exist for. One good answer admits a new replica; pulling the
    only replica of a min-replicas-1 app takes ~50s of continuous failure, because that action
    takes the whole app off ingress."""
    p = mod.READINESS_PROBE
    assert p["successThreshold"] == 1
    assert p["failureThreshold"] * p["periodSeconds"] >= 45
    # A hung check must not overlap the next one.
    assert p["timeoutSeconds"] < p["periodSeconds"]
    # ACA's documented bounds.
    assert 1 <= p["initialDelaySeconds"] <= 60
    assert 1 <= p["periodSeconds"] <= 240
    assert 1 <= p["timeoutSeconds"] <= 240
    assert 1 <= p["successThreshold"] <= 10
    assert 1 <= p["failureThreshold"] <= 10


# ── what it must not destroy ──────────────────────────────────────────────────────────────
def test_the_image_env_and_resources_are_carried_through_untouched():
    """`az containerapp update --yaml` replaces the template. Anything this drops is deleted
    from the running app — the image included."""
    before = _template()
    out = mod.patch(before, "acp-app")
    c_before, c_after = before["containers"][0], out["containers"][0]
    for key in ("name", "image", "resources", "env"):
        assert c_after[key] == c_before[key]
    assert out["scale"] == before["scale"]


def test_a_secret_reference_survives_as_a_reference():
    """Env entries come back from `show` as {name, secretRef}. Flattening one to a value would
    write the secret NAME in as a literal and break the app's database connection."""
    out = mod.patch(_template(), "acp-app")
    env = {e["name"]: e for e in out["containers"][0]["env"]}
    assert env["ACP_DATABASE_URL"] == {"name": "ACP_DATABASE_URL", "secretRef": "database-url"}


def test_someone_elses_liveness_probe_is_preserved():
    t = _template()
    liveness = {"type": "Liveness", "httpGet": {"path": "/healthz", "port": 8077},
                "periodSeconds": 30}
    t["containers"][0]["probes"] = [liveness]
    out = mod.patch(t, "acp-app")
    types = [p["type"] for p in out["containers"][0]["probes"]]
    assert types == ["Liveness", "Readiness"]
    assert out["containers"][0]["probes"][0] == liveness


def test_an_older_readiness_probe_is_replaced_not_duplicated():
    """ACA rejects two probes of the same type, so a re-run must overwrite rather than append."""
    t = _template()
    t["containers"][0]["probes"] = [{"type": "Readiness",
                                     "httpGet": {"path": "/healthz", "port": 8077},
                                     "periodSeconds": 60}]
    out = mod.patch(t, "acp-app")
    probes = out["containers"][0]["probes"]
    assert [p["type"] for p in probes] == ["Readiness"]
    assert probes[0]["httpGet"]["path"] == "/probe/readyz"


def test_the_input_template_is_not_mutated():
    """deploy.sh prints the input on a refusal; mutating it would print something that was
    never the app's actual state."""
    t = _template()
    mod.patch(t, "acp-app")
    assert "probes" not in t["containers"][0]


# ── idempotence ───────────────────────────────────────────────────────────────────────────
def test_a_second_run_reports_nothing_to_do():
    """This runs on EVERY deploy. If it rewrote the template each time it would create a
    revision per deploy for no change, and every deploy would carry the risk of the write."""
    out = mod.patch(_template(), "acp-app")
    assert mod.patch(out, "acp-app") is None


def test_a_drifted_probe_is_not_mistaken_for_the_right_one():
    out = mod.patch(_template(), "acp-app")
    out["containers"][0]["probes"][0]["failureThreshold"] = 1
    assert mod.patch(out, "acp-app") is not None


# ── failing closed ────────────────────────────────────────────────────────────────────────
def test_it_falls_back_to_the_only_container_when_the_name_does_not_match():
    """The ACA CLI derives the container name from the image repository, not the app name, so
    those can legitimately differ. With one container there is nothing to guess."""
    t = _template()
    t["containers"][0]["name"] = "something-else"
    assert mod.patch(t, "acp-app")["containers"][0]["probes"]


def test_the_name_disambiguates_when_there_is_more_than_one_container():
    t = _template()
    t["containers"].append({"name": "sidecar", "image": "x"})
    out = mod.patch(t, "acp-app")
    assert "probes" in out["containers"][0] and "probes" not in out["containers"][1]


def test_it_refuses_to_guess_among_several_containers_when_none_matches():
    """Probing the wrong container of a multi-container app would gate ingress on a sidecar."""
    t = _template()
    t["containers"][0]["name"] = "app"
    t["containers"].append({"name": "sidecar", "image": "x"})
    with pytest.raises(ValueError, match="refusing to guess"):
        mod.patch(t, "acp-app")


@pytest.mark.parametrize("template", [{}, {"containers": []}, {"containers": "acp-app"}, []])
def test_a_template_it_does_not_understand_is_a_refusal_not_a_guess(template):
    with pytest.raises(ValueError):
        mod.patch(template, "acp-app")


# ── the escape hatch ──────────────────────────────────────────────────────────────────────
def test_remove_strips_the_readiness_probe_and_leaves_everything_else():
    """The one way this gate can bite: probes survive an image change, so deploying an image
    that predates /probe/readyz onto a gated app leaves the probe asking for a 404. ACA holds
    traffic on the last healthy revision rather than going dark — it fails safe — but an
    operator still needs a way out that is not hand-editing the template."""
    t = _template()
    liveness = {"type": "Liveness", "httpGet": {"path": "/healthz", "port": 8077}}
    t["containers"][0]["probes"] = [liveness]
    gated = mod.patch(t, "acp-app")
    assert len(gated["containers"][0]["probes"]) == 2

    out = mod.patch(gated, "acp-app", remove=True)
    assert out["containers"][0]["probes"] == [liveness]
    assert out["containers"][0]["image"] == t["containers"][0]["image"]


def test_remove_on_an_ungated_app_is_nothing_to_do():
    assert mod.patch(_template(), "acp-app", remove=True) is None


def test_remove_from_the_command_line_exits_3_when_there_is_no_probe():
    res = _run(json.dumps(_template()), "--container", "acp-app", "--remove")
    assert res.returncode == 3 and res.stdout.strip() == ""


# ── the command-line contract deploy.sh depends on ────────────────────────────────────────
def test_exit_0_prints_a_body_shaped_for_containerapp_update_yaml():
    res = _run(json.dumps(_template()), "--container", "acp-app")
    assert res.returncode == 0, res.stderr
    body = json.loads(res.stdout)
    assert set(body) == {"properties"} and set(body["properties"]) == {"template"}
    assert body["properties"]["template"]["containers"][0]["probes"][0]["type"] == "Readiness"


def test_exit_3_means_already_correct_and_prints_nothing():
    done = json.loads(_run(json.dumps(_template()), "--container", "acp-app").stdout)
    res = _run(json.dumps(done["properties"]["template"]), "--container", "acp-app")
    assert res.returncode == 3
    assert res.stdout.strip() == ""


def test_a_failed_az_show_is_an_empty_stdin_and_must_refuse():
    """`az ... | this` prints nothing when az dies. Refusing is what stops deploy.sh writing a
    template built from nothing."""
    res = _run("")
    assert res.returncode == 1
    assert "no template on stdin" in res.stderr


def test_non_json_on_stdin_refuses():
    res = _run("ERROR: (ResourceNotFound) ...")
    assert res.returncode == 1 and "not JSON" in res.stderr


def test_the_path_and_port_are_overridable_from_the_command_line():
    """deploy.sh owns the ingress port; this must not carry a second copy of it that can drift."""
    res = _run(json.dumps(_template()), "--container", "acp-app", "--port", "9999",
               "--path", "/probe/readyz")
    got = json.loads(res.stdout)["properties"]["template"]["containers"][0]["probes"][0]
    assert got["httpGet"]["port"] == 9999


# ── deploy.sh's step, run for real against a stubbed `az` ─────────────────────────────────
#
# The static half (does the text mention the right path?) proves very little. What matters is
# behavioural and only shows up when the thing runs: that a failure anywhere in here leaves the
# deploy alone, and that a second deploy writes nothing. Nothing below ever reaches Azure.
import os        # noqa: E402
import shutil    # noqa: E402
import textwrap  # noqa: E402

DEPLOY_SH = ACP / "deploy" / "public" / "deploy.sh"

_STUB_AZ = """#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$AZ_LOG"
case "$*" in
  *"containerapp show"*)
     [ "${STUB_SHOW_FAILS:-0}" = "1" ] && { echo "ERROR: (ResourceNotFound) no such app" >&2; exit 1; }
     cat "$STUB_TEMPLATE" ;;
  *"containerapp update"*)
     for a in "$@"; do
       [ "${_next:-}" = "1" ] && { cp "$a" "$YAML_LOG"; _next=0; }
       [ "$a" = "--yaml" ] && _next=1
     done
     [ "${STUB_UPDATE_FAILS:-0}" = "1" ] && { echo "ERROR: (InvalidTemplate) nope" >&2; exit 1; }
     ;;
  *) : ;;
esac
exit 0
"""


def _extract(name: str) -> str:
    """The named shell function, verbatim from deploy.sh — so the test runs the shipped code
    rather than a copy of it that can drift."""
    src = DEPLOY_SH.read_text()
    start = src.index(f"{name}() {{")
    end = src.index("\n}\n", start) + len("\n}\n")
    return src[start:end]


@pytest.fixture()
def probe_step(tmp_path, monkeypatch):
    """Runs deploy.sh's `_apply_readiness_probe` with `az` stubbed. Returns a callable taking
    the app's current template (a dict) and any env overrides."""
    binn = tmp_path / "bin"
    binn.mkdir()
    (binn / "az").write_text(_STUB_AZ)
    (binn / "az").chmod(0o755)
    az_log, yaml_log = tmp_path / "az.log", tmp_path / "applied.json"
    az_log.touch()

    harness = tmp_path / "run.sh"
    harness.write_text(textwrap.dedent(f"""\
        set -euo pipefail
        cd {ACP}
        AZ=(--subscription 11111111-2222-3333-4444-555555555555)
        RG=mdk-accessibility
        APP=acp-app
        """) + _extract("_retry") + _extract("_apply_readiness_probe") + "\n_apply_readiness_probe\n")

    def run(template: dict, **env):
        # Each invocation starts from an empty log, so "did this deploy write?" is answerable
        # for the SECOND deploy and not just the first.
        az_log.write_text("")
        if yaml_log.exists():
            yaml_log.unlink()
        tf = tmp_path / "template.json"
        tf.write_text(json.dumps(template))
        e = {**os.environ, "PATH": f"{binn}:{os.environ['PATH']}",
             "AZ_LOG": str(az_log), "YAML_LOG": str(yaml_log), "STUB_TEMPLATE": str(tf)}
        e.update({k: str(v) for k, v in env.items()})
        res = subprocess.run(["bash", str(harness)], capture_output=True, text=True, env=e)
        res.az_calls = [c for c in az_log.read_text().splitlines() if c.strip()]  # type: ignore[attr-defined]
        res.applied = json.loads(yaml_log.read_text()) if yaml_log.exists() else None  # type: ignore[attr-defined]
        return res

    return run


needs_bash = pytest.mark.skipif(not shutil.which("bash"), reason="bash required")


@needs_bash
def test_the_deploy_step_writes_the_readiness_probe_on_an_ungated_app(probe_step):
    res = probe_step(_template())
    assert res.returncode == 0, res.stderr
    assert any("containerapp update" in c and "--yaml" in c for c in res.az_calls), res.az_calls
    probes = res.applied["properties"]["template"]["containers"][0]["probes"]
    assert [p["type"] for p in probes] == ["Readiness"]
    assert probes[0]["httpGet"]["path"] == "/probe/readyz"
    # and it did not lose the app on the way through
    assert res.applied["properties"]["template"]["containers"][0]["image"].endswith(":abc1234-1756700000")


@needs_bash
def test_a_second_deploy_writes_nothing(probe_step):
    """Probes survive `az containerapp update --image`, so this step is effectively one-time.
    Rewriting the template every deploy would spend a revision, and a write it does not need is
    a risk it does not need to take."""
    first = probe_step(_template())
    already = first.applied["properties"]["template"]
    res = probe_step(already)
    assert res.returncode == 0, res.stderr
    assert not any("containerapp update" in c for c in res.az_calls), res.az_calls
    assert "nothing to do" in res.stdout


@needs_bash
def test_a_failed_read_does_not_fail_the_deploy_and_writes_nothing(probe_step):
    """The deploy has already shipped the image by this point. Taking it down over a probe the
    app ran without until now would be the wrong trade."""
    res = probe_step(_template(), STUB_SHOW_FAILS=1)
    assert res.returncode == 0, res.stderr
    assert not any("containerapp update" in c for c in res.az_calls)
    assert "readiness probe not applied" in res.stderr


@needs_bash
def test_a_failed_write_does_not_fail_the_deploy(probe_step):
    res = probe_step(_template(), STUB_UPDATE_FAILS=1)
    assert res.returncode == 0, res.stderr
    assert "could not write the readiness probe" in res.stderr


@needs_bash
def test_the_step_can_be_turned_off_without_touching_azure_at_all(probe_step):
    res = probe_step(_template(), ACP_SKIP_READINESS_PROBE=1)
    assert res.returncode == 0 and res.az_calls == []
    assert "skipped" in res.stdout


@needs_bash
def test_a_template_it_cannot_understand_leaves_the_app_alone(probe_step):
    """Fail closed: the alternative is writing a template built from a guess."""
    res = probe_step({"containers": [{"name": "a"}, {"name": "b"}]})
    assert res.returncode == 0, res.stderr
    assert not any("containerapp update" in c for c in res.az_calls)
    assert "refusing" in res.stderr
