"""Every `az` call in deploy.sh, rollback.sh and standup.sh must be scoped to one
explicitly-resolved subscription, and no script may mutate the machine-global default.

`az` has no per-invocation profile: `az account set` writes the chosen subscription into
~/.azure/azureProfile.json, a default shared by every shell, CI step and concurrent agent on
the box. All three scripts got this wrong, in three different ways.

deploy.sh pinned its target with `az account set`. Observed failure (2026-07-09): a deploy
built and pushed its image, then died at "3/5 registry creds" with

    ERROR: The resource with name 'mdkaccessibilityacr' and type
    'Microsoft.ContainerRegistry/registries' could not be found in subscription
    'AZLABSV2.0-Sandbox(POC)'

because another process ran `az account set` between step 2 and step 3. The converse also bit:
a plain `bash deploy.sh` silently repointed the operator's own shell at the demo subscription.

rollback.sh never called `az account set` -- it passed `--subscription`, but only when
ACP_SUBSCRIPTION was set:

    SUB_ARG=()
    [ -n "${ACP_SUBSCRIPTION:-}" ] && SUB_ARG=(--subscription "$ACP_SUBSCRIPTION")

Unset (the normal case -- nobody exports it before an emergency rollback) the array was EMPTY,
and the outcome depended on which bash `#!/usr/bin/env bash` found:
  * bash 3.2, still /bin/bash on macOS: "${SUB_ARG[@]}" is an unbound variable under `set -u`,
    so even the read-only `rollback.sh --list` died at the first az call;
  * bash >= 4.4: it expanded to nothing, so every call followed the global default.

standup.sh called `az account set` like deploy.sh, but with far more at stake: `bash standup.sh
teardown` runs `az group delete --yes --no-wait` -- irreversible, and it asks nothing. RG comes
from $ACP_RG, the SAME variable deploy.sh reads, where it defaults to the PRODUCTION group
`mdk-accessibility`. Export ACP_RG for a deploy, run teardown in that shell, and acp-app, the
ACR, Postgres, Langfuse, Ollama, Redis and the blob store go with it. It now confirms first.

All three now resolve the subscription once, to its immutable ID (a rename cannot retarget a
running deploy), fail closed when nothing resolves, and splice `--subscription <id>` into every
call. The destructive path is exercised only against a stubbed `az` -- never against Azure.
"""
from __future__ import annotations
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DEPLOY_SH = ROOT / "deploy" / "public" / "deploy.sh"
ROLLBACK_SH = ROOT / "deploy" / "public" / "rollback.sh"
STANDUP_SH = ROOT / "deploy" / "azure-temporal" / "standup.sh"
SCRIPTS = [DEPLOY_SH, ROLLBACK_SH, STANDUP_SH]

# An `az ...` invocation, matched only in COMMAND position: at the start of a line, or right
# after a construct that begins a command (`$(`, `&&`, `||`, `;`, `|`, `if`, `then`, `do`,
# `_retry`). Matching a bare `az\s` anywhere would also hit the word "az" inside quoted prose --
# e.g. the error string `... (az login?)` -- which is not a call.
_AZ_CALL = re.compile(r"(?:^|\$\(|&&|\|\||;|\||\bif\b|\bthen\b|\bdo\b|_retry\s)\s*az\s")

# The preflight resolvers are the ONLY calls allowed to run unscoped: they are what *determines*
# the scope. Both are `az account show`, and neither writes anything.
_RESOLVER = re.compile(r"az account show\b")


def _code(path: Path) -> list[tuple[int, str]]:
    """(1-indexed lineno, text) for lines that are not blank and not pure comments."""
    return [(i, ln) for i, ln in enumerate(path.read_text().splitlines(), 1)
            if ln.strip() and not ln.lstrip().startswith("#")]


def _src(path: Path) -> str:
    return "\n".join(ln for _, ln in _code(path))


def _ids(paths):
    return [p.name for p in paths]


# ---------------------------------------------------------------- static invariants

@pytest.mark.parametrize("script", SCRIPTS, ids=_ids(SCRIPTS))
def test_no_global_subscription_mutation(script):
    """`az account set` writes a machine-global default. Never in executable code."""
    offenders = [(n, ln.strip()) for n, ln in _code(script) if "az account set" in ln]
    assert offenders == [], (
        f"{script.name} mutates the shared az default; use --subscription per call:\n"
        + "\n".join(f"  L{n}: {t}" for n, t in offenders)
    )


@pytest.mark.parametrize("script", SCRIPTS, ids=_ids(SCRIPTS))
def test_every_az_call_is_subscription_scoped(script):
    """Every `az` call carries "${AZ[@]}" -- except the preflight resolvers that compute it."""
    unscoped = [
        (n, ln.strip()) for n, ln in _code(script)
        if _AZ_CALL.search(ln) and "${AZ[@]}" not in ln and not _RESOLVER.search(ln)
    ]
    assert unscoped == [], (
        f"these {script.name} calls would follow the machine-global default subscription:\n"
        + "\n".join(f"  L{n}: {t}" for n, t in unscoped)
    )


@pytest.mark.parametrize("script", SCRIPTS, ids=_ids(SCRIPTS))
def test_the_scope_array_is_defined_before_first_use(script):
    code = _code(script)
    defined = next((n for n, ln in code if re.match(r"\s*AZ=\(", ln)), None)
    assert defined, 'preflight must define the scope array: AZ=(--subscription "$SUB")'
    # >=, not >: the defining line carries a trailing comment that names "${AZ[@]}".
    first_use = next((n for n, ln in code if "${AZ[@]}" in ln), None)
    assert first_use and first_use >= defined, "AZ[@] is used before it is defined"


@pytest.mark.parametrize("script", SCRIPTS, ids=_ids(SCRIPTS))
def test_scope_pins_the_immutable_id_not_the_name(script):
    """A subscription can be renamed mid-run; its ID cannot. Resolve name -> id once, pin the id."""
    src = _src(script)
    assert re.search(r'SUB="\$\(az account show .*--query id -o tsv', src), \
        f"{script.name} preflight must resolve the subscription to its ID"
    assert 'AZ=(--subscription "$SUB")' in src, "the scope array must pin the resolved ID"


@pytest.mark.parametrize("script", SCRIPTS, ids=_ids(SCRIPTS))
def test_preflight_fails_closed_when_no_subscription_resolves(script):
    """A script that cannot name its target must abort, not use whatever az defaults to.

    Every resolver (`SUB="$(az account show ...)"`, which swallows failure with `|| true`) must be
    followed by a guard that exits. deploy.sh and rollback.sh have two resolvers -- one for the
    explicit ACP_SUBSCRIPTION path, one for the implicit az-default path. standup.sh always has a
    subscription name (it defaults one), so it has a single resolver. Tie the counts together
    rather than hard-coding 2, so a new resolver cannot be added without its guard.
    """
    src = _src(script)
    resolvers = re.findall(r'SUB="\$\(az account show', src)
    guards = re.findall(r'\[ -n "\$SUB" \] \|\| \{[^}]*exit 1', src)
    assert len(resolvers) >= 1, f"{script.name}: no subscription resolver found"
    assert len(guards) == len(resolvers), (
        f"{script.name}: {len(resolvers)} resolver(s) but {len(guards)} guard(s) -- every "
        f"resolver must abort when the subscription does not resolve"
    )


@pytest.mark.parametrize("script", SCRIPTS, ids=_ids(SCRIPTS))
def test_the_scope_array_is_never_empty(script):
    """An empty array is the rollback.sh bug: unbound under bash 3.2, silently unscoped after."""
    assert not re.search(r"^\s*(AZ|SUB_ARG)=\(\)\s*$", _src(script), re.M), \
        f"{script.name} must not build the scope array conditionally from an empty one"


@pytest.mark.parametrize("script", SCRIPTS, ids=_ids(SCRIPTS))
def test_write_path_calls_are_scoped(script):
    """The calls that actually mutate Azure are the ones a mis-scope would damage.

    `group delete` heads the list deliberately: it is the only irreversible one.
    """
    src = _src(script)
    for verb in ("group delete", "group create",
                 "containerapp update", "containerapp create", "containerapp secret set",
                 "containerapp registry set", "containerapp env create",
                 "acr build", "acr create", "acr import",
                 "postgres flexible-server create", "postgres flexible-server parameter set"):
        for m in re.finditer(rf"az {re.escape(verb)}(.*)", src):
            assert "${AZ[@]}" in m.group(0), f"{script.name}: unscoped write call: az {verb}"


# ---------------------------------------------------------------- executable behaviour
# The static checks above can only see the text. These run rollback.sh for real against a stubbed
# `az`, which is what catches an unbound-variable death that no amount of grepping would reveal.

_STUB_AZ = """#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$AZ_LOG"
case "$*" in
  *"account show"*"--query id"*)   echo "11111111-2222-3333-4444-555555555555" ;;
  *"account show"*"--query name"*) echo "Stub Subscription" ;;
  *"revision list"*"-o json"*)
     echo '[{"rev":"r2","img":"acr.io/acp-app:new","created":"2026-07-10T03:42:29Z","traffic":100,"state":"Running"},'
     echo ' {"rev":"r1","img":"acr.io/acp-app:old","created":"2026-07-10T01:00:00Z","traffic":0,"state":"Deactivated"}]' ;;
  *) : ;;
esac
exit 0
"""

RESOLVED_ID = "11111111-2222-3333-4444-555555555555"


@pytest.fixture()
def stub_az(tmp_path, monkeypatch):
    """Put a fake `az` first on PATH and return the file its calls are logged to."""
    binn = tmp_path / "bin"
    binn.mkdir()
    (binn / "az").write_text(_STUB_AZ)
    (binn / "az").chmod(0o755)
    log = tmp_path / "az.log"
    log.touch()
    monkeypatch.setenv("AZ_LOG", str(log))
    monkeypatch.setenv("PATH", f"{binn}:{os.environ['PATH']}")
    monkeypatch.delenv("ACP_SUBSCRIPTION", raising=False)   # the incident case: not exported
    return log


@pytest.mark.skipif(not shutil.which("bash"), reason="bash required")
def test_rollback_list_runs_without_acp_subscription(stub_az):
    """Regression: `rollback.sh --list` died with `SUB_ARG[@]: unbound variable` under bash 3.2
    whenever ACP_SUBSCRIPTION was unset -- i.e. in the incident it exists to resolve."""
    out = subprocess.run(["bash", str(ROLLBACK_SH), "--list"], capture_output=True, text=True)
    assert "unbound variable" not in out.stderr, out.stderr
    assert out.returncode == 0, f"rollback.sh --list failed:\n{out.stderr}"


@pytest.mark.skipif(not shutil.which("bash"), reason="bash required")
def test_rollback_scopes_every_call_to_the_resolved_id(stub_az):
    """With nothing exported, every call must still name the subscription it resolved."""
    subprocess.run(["bash", str(ROLLBACK_SH), "--list"], capture_output=True, text=True, check=True)
    calls = [c for c in stub_az.read_text().splitlines() if c.strip()]
    assert calls, "no az calls were made"
    assert not any("account set" in c for c in calls), "rollback.sh mutated the global default"
    for call in calls:
        if call.startswith("account show") and f"--subscription {RESOLVED_ID}" not in call:
            continue   # the resolver itself, which discovers the ID
        assert f"--subscription {RESOLVED_ID}" in call, f"unscoped az call: {call}"


@pytest.mark.skipif(not shutil.which("bash"), reason="bash required")
def test_rollback_fails_closed_when_the_subscription_does_not_resolve(tmp_path, monkeypatch):
    """No resolvable subscription => abort. Never fall through to the az default."""
    binn = tmp_path / "bin"
    binn.mkdir()
    (binn / "az").write_text("#!/usr/bin/env bash\nexit 1\n")   # every az call fails silently
    (binn / "az").chmod(0o755)
    monkeypatch.setenv("PATH", f"{binn}:{os.environ['PATH']}")
    monkeypatch.delenv("ACP_SUBSCRIPTION", raising=False)
    out = subprocess.run(["bash", str(ROLLBACK_SH), "--list"], capture_output=True, text=True)
    assert out.returncode == 1
    assert "refusing to roll back" in out.stderr


# ---------------------------------------------------------------- standup.sh teardown guard
# `bash standup.sh teardown` runs `az group delete --yes --no-wait`: irreversible, asks nothing.
# It used to read RG from $ACP_RG -- the SAME variable deploy/public/deploy.sh reads, where it
# defaults to the PRODUCTION group `mdk-accessibility`. RG now comes from $ACP_TEMPORAL_RG and a
# stray $ACP_RG is refused outright (tests/test_deploy_env_namespacing.py), but namespacing only
# removes one way to aim at the wrong group; a mistyped ACP_TEMPORAL_RG still does. Hence the
# confirmation. These tests run the real script against a stubbed `az` -- nothing is ever deleted.

_STUB_AZ_STANDUP = """#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$AZ_LOG"
case "$*" in
  *"account show"*"--query id"*)   echo "11111111-2222-3333-4444-555555555555" ;;
  *"account show"*"--query name"*) echo "Stub Subscription" ;;
  *"resource list"*)               echo "some-precious-resource" ;;
  *) : ;;
esac
exit 0
"""


@pytest.fixture()
def stub_standup(tmp_path, monkeypatch):
    binn = tmp_path / "bin"
    binn.mkdir()
    (binn / "az").write_text(_STUB_AZ_STANDUP)
    (binn / "az").chmod(0o755)
    log = tmp_path / "az.log"
    log.touch()
    monkeypatch.setenv("AZ_LOG", str(log))
    monkeypatch.setenv("PATH", f"{binn}:{os.environ['PATH']}")
    monkeypatch.delenv("ACP_CONFIRM_TEARDOWN", raising=False)
    return log


# standup.sh addresses the Temporal stack through ACP_TEMPORAL_*, and REFUSES to run when a
# public-demo name (ACP_RG, ACP_ACR, ACP_APP, ACP_ACA_ENV) is exported -- see
# tests/test_deploy_env_namespacing.py. Drive it by the right variable, and scrub the others from
# the inherited environment, or these tests exercise the ambiguity guard instead of the
# confirmation guard and pass for the wrong reason.
_PUBLIC_NAMES = ("ACP_RG", "ACP_ACR", "ACP_APP", "ACP_ACA_ENV", "ACP_ENV")


def _run_standup(env_extra=None):
    env = {k: v for k, v in os.environ.items() if k not in _PUBLIC_NAMES}
    env.update(env_extra or {})
    # stdin closed => non-interactive, the shape a stray `bash standup.sh teardown` takes in a
    # script or an agent's shell.
    return subprocess.run(["bash", str(STANDUP_SH), "teardown"],
                          capture_output=True, text=True, env=env, stdin=subprocess.DEVNULL)


@pytest.mark.skipif(not shutil.which("bash"), reason="bash required")
def test_teardown_refuses_non_interactively_without_confirmation(stub_standup):
    """The catastrophic path: unconfirmed, non-interactive teardown must delete nothing."""
    out = _run_standup()
    assert out.returncode == 1
    assert "refusing to tear down" in out.stderr
    calls = stub_standup.read_text()
    assert "group delete" not in calls, "teardown deleted a resource group without confirmation"


@pytest.mark.skipif(not shutil.which("bash"), reason="bash required")
def test_teardown_refuses_when_confirmation_names_a_different_group(stub_standup):
    """Confirming one group must not authorise deleting another.

    Drive the wrong group through ACP_TEMPORAL_RG, not ACP_RG: the latter is refused earlier by
    the namespacing guard, which would make this pass without ever reaching the confirmation.
    """
    out = _run_standup({"ACP_TEMPORAL_RG": "mdk-accessibility",
                        "ACP_CONFIRM_TEARDOWN": "rg-acp-temporal"})
    assert out.returncode == 1
    assert "refusing to tear down" in out.stderr, out.stderr   # the CONFIRMATION guard, not the other
    assert "group delete" not in stub_standup.read_text()


@pytest.mark.skipif(not shutil.which("bash"), reason="bash required")
def test_teardown_proceeds_when_confirmation_matches_and_is_scoped(stub_standup):
    """With an explicit, matching confirmation it proceeds -- scoped to the resolved subscription."""
    out = _run_standup({"ACP_TEMPORAL_RG": "rg-acp-temporal",
                        "ACP_CONFIRM_TEARDOWN": "rg-acp-temporal"})
    assert out.returncode == 0, out.stderr
    deletes = [c for c in stub_standup.read_text().splitlines() if c.startswith("group delete")]
    assert len(deletes) == 1, f"expected exactly one group delete, got {deletes}"
    assert f"--subscription {RESOLVED_ID}" in deletes[0]
    assert "-n rg-acp-temporal" in deletes[0]


@pytest.mark.skipif(not shutil.which("bash"), reason="bash required")
def test_standup_never_mutates_the_global_default(stub_standup):
    _run_standup({"ACP_TEMPORAL_RG": "rg-acp-temporal",
                  "ACP_CONFIRM_TEARDOWN": "rg-acp-temporal"})
    assert "account set" not in stub_standup.read_text()
