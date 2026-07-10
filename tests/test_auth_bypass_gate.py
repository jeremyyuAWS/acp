"""The X-E2E-Key / X-Demo-Key auth bypasses must FAIL CLOSED.

Regression under test: `E2E_KEY` was `(key or None) if not IS_PROD else None`, and `IS_PROD`
came from `ACP_ENV`. Nothing ever set `ACP_ENV` on the deployed container — the name was
already taken by deploy.sh for the Container Apps *environment name* — so `IS_PROD` was False
in production and the X-E2E-Key gate bypass (api/app.py) was live on the public demo.

A security control must never be enabled by the ABSENCE of a variable. The bypass now
requires an explicit opt-in AND a non-production deploy env.
"""
from __future__ import annotations
import importlib
import sys
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

_KEYS = ("ACP_E2E_KEY", "ACP_ENABLE_TEST_BYPASS", "ACP_DEPLOY_ENV", "ACP_ENV")


@pytest.fixture(autouse=True)
def _restore_core_module():
    """Put the ORIGINAL `core` module back after every test in this file.

    `_core()` re-imports core to re-read env at import time, which replaces
    sys.modules["core"] with a brand-new module object owning its own Store and its own
    in-memory scan-token registry. Modules that already did `import core` (handlers, worker)
    keep a reference to the OLD object. Leaving the new one installed means a later test
    registers a Drive token on one `core` while the worker reads another — which is exactly
    how this file turned tests/test_jobs.py red on main (drive_token=None, job='dead') while
    still passing when run in isolation, because import order differs between a single-file
    run and the full suite.
    """
    original = sys.modules.get("core")
    yield
    if original is not None:
        sys.modules["core"] = original
    else:
        sys.modules.pop("core", None)


def _core(monkeypatch, **env):
    """Re-import core with a clean, explicit environment (it reads env at import time)."""
    for k in _KEYS:
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    sys.modules.pop("core", None)
    return importlib.import_module("core")


def test_bypass_off_by_default_even_with_a_key_set(monkeypatch):
    """The exact production shape before this fix: key present, no env flags at all."""
    core = _core(monkeypatch, ACP_E2E_KEY="s3cret")
    assert core.IS_PROD is False            # unchanged: no deploy-env var set
    assert core.TEST_BYPASS_ENABLED is False
    assert core.E2E_KEY is None             # ← the bypass is now closed


def test_bypass_requires_explicit_opt_in(monkeypatch):
    core = _core(monkeypatch, ACP_E2E_KEY="s3cret", ACP_ENABLE_TEST_BYPASS="true")
    assert core.TEST_BYPASS_ENABLED is True
    assert core.E2E_KEY == "s3cret"


def test_opt_in_is_refused_in_production(monkeypatch):
    """Defence in depth: even an explicit opt-in cannot reopen the backdoor in prod."""
    core = _core(monkeypatch, ACP_E2E_KEY="s3cret",
                 ACP_ENABLE_TEST_BYPASS="true", ACP_DEPLOY_ENV="production")
    assert core.IS_PROD is True
    assert core.TEST_BYPASS_ENABLED is False
    assert core.E2E_KEY is None


def test_opt_in_without_a_key_grants_nothing(monkeypatch):
    core = _core(monkeypatch, ACP_ENABLE_TEST_BYPASS="true")
    assert core.TEST_BYPASS_ENABLED is True
    assert core.E2E_KEY is None             # nothing to compare X-E2E-Key against


@pytest.mark.parametrize("val", ["1", "true", "TRUE", "yes", " true "])
def test_opt_in_accepts_common_truthy_spellings(monkeypatch, val):
    core = _core(monkeypatch, ACP_E2E_KEY="k", ACP_ENABLE_TEST_BYPASS=val)
    assert core.E2E_KEY == "k"


@pytest.mark.parametrize("val", ["", "0", "false", "no", "maybe"])
def test_opt_in_rejects_everything_else(monkeypatch, val):
    core = _core(monkeypatch, ACP_E2E_KEY="k", ACP_ENABLE_TEST_BYPASS=val)
    assert core.E2E_KEY is None


@pytest.mark.parametrize("var", ["ACP_DEPLOY_ENV", "ACP_ENV"])
@pytest.mark.parametrize("val", ["production", "prod", "PROD"])
def test_is_prod_reads_canonical_and_legacy_names(monkeypatch, var, val):
    core = _core(monkeypatch, **{var: val})
    assert core.IS_PROD is True


def test_deploy_script_stamps_the_production_flag():
    """deploy.sh only ever ships the public demo, so it must mark the app as production —
    under ACP_DEPLOY_ENV, not ACP_ENV (that name is the ACA environment name in this script)."""
    sh = (ACP / "deploy" / "public" / "deploy.sh").read_text()
    assert 'DEPLOY_ENV_ENV="ACP_DEPLOY_ENV=production"' in sh
    assert sh.count("$DEPLOY_ENV_ENV") >= 2          # wired into both update and create
