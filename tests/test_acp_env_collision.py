"""`ACP_ENV` must mean exactly one thing.

It used to mean two. `api/core.py` read it as the DEPLOYMENT environment (`IS_PROD`), while
`deploy/public/deploy.sh` and `deploy/azure-temporal/standup.sh` read the same name as the
Azure Container Apps ENVIRONMENT NAME:

    ENVNAME="${ACP_ENV:-acp-temporal-env}"

And `docs/production-hardening.md` told operators, as its very first hardening step:

    ACP_ENV=production

Follow that and nothing you intended happens:

  * the deploy scripts read "production" as an ACA environment name. `standup.sh` runs
    `az containerapp env show -n production`, which fails, and then
    `az containerapp env create -n production` -- creating a new, empty ACA environment;
  * `ACP_ENV` is never passed through to the container, so `core.IS_PROD` stayed False on the
    public demo and the `X-E2E-Key` / `X-Demo-Key` auth bypasses stayed live.

The security fix (PR 47) worked around the collision by inventing `ACP_DEPLOY_ENV`. This closes
it properly: the ACA environment name is `ACP_ACA_ENV`, the deploy scripts REFUSE to run when
the ambiguous `ACP_ENV` is set, and the docs say `ACP_DEPLOY_ENV`. `core.IS_PROD` keeps reading
`ACP_ENV` as a legacy alias, because that can only make IS_PROD *more* likely true -- the safe
direction for a container already setting it.
"""
from __future__ import annotations
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DEPLOY_SH = ROOT / "deploy" / "public" / "deploy.sh"
STANDUP_SH = ROOT / "deploy" / "azure-temporal" / "standup.sh"
CORE_PY = ROOT / "api" / "core.py"
HARDENING_MD = ROOT / "docs" / "production-hardening.md"

DEPLOY_SCRIPTS = [DEPLOY_SH, STANDUP_SH]

sys.path.insert(0, str(ROOT / "api"))


def _code(path: Path) -> str:
    """Executable lines only -- comments here discuss ACP_ENV at length, by design."""
    return "\n".join(ln for ln in path.read_text().splitlines()
                     if ln.strip() and not ln.lstrip().startswith("#"))


# ---------------------------------------------------------------- the scripts

@pytest.mark.parametrize("script", DEPLOY_SCRIPTS, ids=lambda p: p.name)
def test_aca_environment_name_no_longer_reads_acp_env(script):
    """ENVNAME must come from ACP_ACA_ENV. Reading $ACP_ENV is what created the collision."""
    src = _code(script)
    assert not re.search(r'ENVNAME="\$\{ACP_ENV[:-]', src), \
        f"{script.name} still resolves the ACA environment name from $ACP_ENV"
    assert re.search(r'ENVNAME="\$\{ACP_ACA_ENV[:-]', src), \
        f"{script.name} must resolve the ACA environment name from $ACP_ACA_ENV"


@pytest.mark.parametrize("script", DEPLOY_SCRIPTS, ids=lambda p: p.name)
def test_scripts_refuse_the_ambiguous_name(script):
    """Guessing which meaning was intended is worse than refusing."""
    src = _code(script)
    assert re.search(r'if \[ -n "\$\{ACP_ENV:-\}" \]; then', src), \
        f"{script.name} must refuse to run when ACP_ENV is set"
    assert "exit 1" in src


# ---------------------------------------------------------------- the app

def test_is_prod_still_honours_the_legacy_alias(monkeypatch):
    """Removing the alias could silently drop a container out of production mode on upgrade."""
    import importlib
    for var in ("ACP_DEPLOY_ENV", "ACP_ENV", "ACP_ENABLE_TEST_BYPASS", "ACP_E2E_KEY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("ACP_ENV", "production")
    original = sys.modules.get("core")
    try:
        sys.modules.pop("core", None)
        core = importlib.import_module("core")
        assert core.IS_PROD is True, "the legacy ACP_ENV alias must still mark production"
    finally:
        if original is not None:
            sys.modules["core"] = original
        else:
            sys.modules.pop("core", None)


def test_canonical_name_is_acp_deploy_env():
    src = _code(CORE_PY)
    m = re.search(r'IS_PROD = \(os\.environ\.get\("([A-Z_]+)"\)', src)
    assert m and m.group(1) == "ACP_DEPLOY_ENV", \
        "ACP_DEPLOY_ENV must be read first -- it is the canonical name"


# ---------------------------------------------------------------- the docs
# The docs are not incidental here: `ACP_ENV=production` was step 1 of the hardening
# checklist, and following it is what left the bypass live.

def test_hardening_doc_no_longer_instructs_the_ambiguous_name():
    text = HARDENING_MD.read_text()
    instructions = [ln for ln in text.splitlines()
                    if re.match(r"^\s*ACP_ENV\s*=", ln)]
    assert instructions == [], (
        "docs/production-hardening.md still instructs operators to set ACP_ENV:\n"
        + "\n".join(f"  {ln}" for ln in instructions)
    )
    assert "ACP_DEPLOY_ENV=production" in text


# ---------------------------------------------------------------- executable behaviour

@pytest.mark.skipif(not shutil.which("bash"), reason="bash required")
@pytest.mark.parametrize("script", DEPLOY_SCRIPTS, ids=lambda p: p.name)
def test_script_actually_exits_when_acp_env_is_set(script, tmp_path, monkeypatch):
    """Run the real script with ACP_ENV set. It must die in preflight, before any az call.

    A stub `az` that fails on every call proves the refusal happens first: if the guard were
    missing, the script would get further and the error would be an az error, not ours.
    """
    binn = tmp_path / "bin"
    binn.mkdir()
    (binn / "az").write_text("#!/usr/bin/env bash\necho 'STUB AZ WAS CALLED' >&2\nexit 1\n")
    (binn / "az").chmod(0o755)
    env = dict(os.environ, PATH=f"{binn}:{os.environ['PATH']}", ACP_ENV="production")
    env.pop("ACP_ACA_ENV", None)

    out = subprocess.run(["bash", str(script)], capture_output=True, text=True,
                         env=env, stdin=subprocess.DEVNULL)
    assert out.returncode == 1
    assert "ACP_ENV is set" in out.stderr, out.stderr
    assert "ACP_ACA_ENV" in out.stderr and "ACP_DEPLOY_ENV" in out.stderr
    assert "STUB AZ WAS CALLED" not in out.stderr, \
        f"{script.name} reached an az call before refusing the ambiguous ACP_ENV"
