"""No environment variable may address two different pieces of infrastructure.

There are two stacks:

  * the PUBLIC DEMO   -- deploy/public/deploy.sh and deploy/public/rollback.sh
  * TEMPORAL          -- deploy/azure-temporal/standup.sh

They shared four variable names with different defaults: ACP_RG, ACP_ACR, ACP_APP and
ACP_ACA_ENV. The dangerous one was ACP_RG:

    export ACP_RG=mdk-accessibility        # entirely reasonable, for a deploy
    bash deploy/azure-temporal/standup.sh teardown

    -> az group delete -n mdk-accessibility --yes --no-wait

which takes acp-app, the ACR, Postgres, Langfuse, Ollama, Redis and the blob store with it.

standup.sh now reads ACP_TEMPORAL_* and refuses to run when a public-demo name is exported.
deploy.sh and rollback.sh keep the unprefixed names: they address the same stack as each other,
so sharing is correct there -- and is asserted below, since a rollback that reads a different
app than the deploy is its own bug.

The last test is the general one: it re-derives every `VAR="${ACP_X:-default}"` binding from all
three scripts and fails if any single ACP_X carries two different defaults. That is what catches
the NEXT collision. ACP_ACA_ENV was introduced one commit earlier to FIX the ACP_ENV collision,
and immediately created a smaller one -- a test asserting only the four known names would have
passed.
"""
from __future__ import annotations
import os
import re
import shutil
import subprocess
from collections import defaultdict
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DEPLOY_SH = ROOT / "deploy" / "public" / "deploy.sh"
ROLLBACK_SH = ROOT / "deploy" / "public" / "rollback.sh"
STANDUP_SH = ROOT / "deploy" / "azure-temporal" / "standup.sh"

PUBLIC_STACK = [DEPLOY_SH, ROLLBACK_SH]
ALL_SCRIPTS = [DEPLOY_SH, ROLLBACK_SH, STANDUP_SH]

# Names that address the public-demo stack. standup.sh must neither read nor tolerate them.
PUBLIC_NAMES = ["ACP_RG", "ACP_ACR", "ACP_APP", "ACP_ACA_ENV"]

# Deliberately shared: one Azure subscription holds both stacks, and both scripts mean the same
# thing by it. Sharing a name is only a bug when the referents differ.
INTENTIONALLY_SHARED = {"ACP_SUBSCRIPTION", "ACP_SUB"}

# VAR="${ACP_X:-default}"  -- captures the env var and its default, ignoring `${ACP_X:+...}` and
# bare `${ACP_X}` uses. The default may itself contain ${...}, so match to the last brace on the
# line and strip the trailing quote/comment.
_BINDING = re.compile(r'^\s*([A-Z_]+)="\$\{(ACP_[A-Z_]+):-(.*)\}"')


def _code(path: Path) -> list[str]:
    return [ln for ln in path.read_text().splitlines()
            if ln.strip() and not ln.lstrip().startswith("#")]


def _bindings(path: Path) -> dict[str, str]:
    """{env var: default} for every `VAR="${ACP_X:-default}"` in the script."""
    out = {}
    for ln in _code(path):
        m = _BINDING.match(ln)
        if m:
            out[m.group(2)] = m.group(3).strip()
    return out


# ---------------------------------------------------------------- standup.sh is namespaced

@pytest.mark.parametrize("name", PUBLIC_NAMES)
def test_standup_does_not_read_public_stack_names(name):
    assert name not in _bindings(STANDUP_SH), \
        f"standup.sh reads {name}, which addresses the public demo stack"


@pytest.mark.parametrize("name", PUBLIC_NAMES)
def test_standup_reads_the_namespaced_name(name):
    prefixed = name.replace("ACP_", "ACP_TEMPORAL_", 1)
    assert prefixed in _bindings(STANDUP_SH), f"standup.sh must read {prefixed}"


# ---------------------------------------------------------------- the public pair agrees

@pytest.mark.parametrize("name", ["ACP_RG", "ACP_APP"])
def test_deploy_and_rollback_agree(name):
    """rollback.sh must target the app deploy.sh deployed. Same name, same default."""
    d, r = _bindings(DEPLOY_SH), _bindings(ROLLBACK_SH)
    assert name in d and name in r, f"{name} must be read by both deploy.sh and rollback.sh"
    assert d[name] == r[name], (
        f"{name} defaults differ: deploy.sh={d[name]!r} rollback.sh={r[name]!r} -- "
        f"a rollback would target a different app than the deploy"
    )


# ---------------------------------------------------------------- the general invariant

def test_no_env_var_addresses_two_different_things():
    """One ACP_* name, one referent. This is the test that catches the next collision."""
    seen: dict[str, dict[str, str]] = defaultdict(dict)
    for script in ALL_SCRIPTS:
        for var, default in _bindings(script).items():
            seen[var][script.name] = default

    collisions = {
        var: per_script for var, per_script in seen.items()
        if var not in INTENTIONALLY_SHARED and len(set(per_script.values())) > 1
    }
    assert not collisions, "these env vars mean different things in different scripts:\n" + "\n".join(
        f"  {var}:\n" + "\n".join(f"    {s} -> {d!r}" for s, d in per.items())
        for var, per in sorted(collisions.items())
    )


# ---------------------------------------------------------------- executable behaviour

@pytest.mark.skipif(not shutil.which("bash"), reason="bash required")
@pytest.mark.parametrize("name", PUBLIC_NAMES)
def test_standup_refuses_when_a_public_stack_name_is_exported(name, tmp_path, monkeypatch):
    """Refuse, don't ignore: a set ACP_RG means the operator thinks it addresses this script.

    The stub `az` fails on every call and announces itself, so we also prove the refusal happens
    in preflight -- before anything reaches Azure.
    """
    binn = tmp_path / "bin"
    binn.mkdir()
    (binn / "az").write_text("#!/usr/bin/env bash\necho 'STUB AZ WAS CALLED' >&2\nexit 1\n")
    (binn / "az").chmod(0o755)

    env = dict(os.environ, PATH=f"{binn}:{os.environ['PATH']}")
    for v in PUBLIC_NAMES + ["ACP_ENV"]:
        env.pop(v, None)
    env[name] = "mdk-accessibility"

    out = subprocess.run(["bash", str(STANDUP_SH), "teardown"], capture_output=True, text=True,
                         env=env, stdin=subprocess.DEVNULL)
    assert out.returncode == 1
    assert name in out.stderr and "ACP_TEMPORAL_" in out.stderr, out.stderr
    assert "STUB AZ WAS CALLED" not in out.stderr, "reached an az call before refusing"


@pytest.mark.skipif(not shutil.which("bash"), reason="bash required")
def test_the_exact_catastrophe_is_refused(tmp_path):
    """`export ACP_RG=mdk-accessibility; standup.sh teardown` must delete nothing."""
    binn = tmp_path / "bin"
    binn.mkdir()
    log = tmp_path / "az.log"
    (binn / "az").write_text(
        '#!/usr/bin/env bash\nprintf "%s\\n" "$*" >> "$AZ_LOG"\n'
        'case "$*" in *"account show"*) echo "11111111-2222-3333-4444-555555555555" ;; esac\nexit 0\n')
    (binn / "az").chmod(0o755)
    log.touch()

    env = dict(os.environ, PATH=f"{binn}:{os.environ['PATH']}", AZ_LOG=str(log),
               ACP_RG="mdk-accessibility", ACP_CONFIRM_TEARDOWN="mdk-accessibility")
    env.pop("ACP_ENV", None)

    out = subprocess.run(["bash", str(STANDUP_SH), "teardown"], capture_output=True, text=True,
                         env=env, stdin=subprocess.DEVNULL)
    assert out.returncode == 1
    assert "group delete" not in log.read_text(), "IT DELETED THE PRODUCTION RESOURCE GROUP"
