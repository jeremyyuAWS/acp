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

_KEYS = ("ACP_E2E_KEY", "ACP_ENABLE_TEST_BYPASS", "ACP_DEPLOY_ENV", "ACP_ENV", "ACP_MONITOR_KEY")


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


# ── the monitoring credential, which is the OPPOSITE case ────────────────────────────
#
# Everything above is about a credential that must go dead in production. ACP_MONITOR_KEY is
# the one that must stay alive there, and the distinction is the whole reason it exists: the
# production monitor's deep checks authenticated with X-E2E-Key, so they were refused by the
# very control the tests above assert. The choice was to reopen the backdoor or to give
# monitoring its own door that grants only counts. These tests pin the second.

def test_the_monitor_key_survives_production(monkeypatch):
    """The bug this fixes, stated as a test: in production E2E_KEY is None (asserted above) and
    MONITOR_KEY is not. A deep check that needs the first can never run where it matters."""
    core = _core(monkeypatch, ACP_E2E_KEY="s3cret", ACP_MONITOR_KEY="m0nitor",
                 ACP_DEPLOY_ENV="production")
    assert core.IS_PROD is True
    assert core.E2E_KEY is None              # the gate bypass stays shut, as it must
    assert core.MONITOR_KEY == "m0nitor"     # and the read-only door stays open


def test_the_monitor_key_does_not_depend_on_the_test_bypass_opt_in(monkeypatch):
    """It must not be coupled to ACP_ENABLE_TEST_BYPASS — that coupling is exactly what made
    the old deep checks unrunnable, and it would be an easy 'consistency' cleanup to add."""
    core = _core(monkeypatch, ACP_MONITOR_KEY="m0nitor")
    assert core.TEST_BYPASS_ENABLED is False
    assert core.MONITOR_KEY == "m0nitor"


def test_the_monitor_key_has_no_default(monkeypatch):
    """A monitoring credential with a well-known fallback is a backdoor. Unset must mean the
    route is closed, not that it is open to a documented default — contrast ALERT_KEY, which
    does ship one and is the pattern NOT to copy here."""
    core = _core(monkeypatch)
    assert core.MONITOR_KEY is None


def test_the_monitor_route_is_public_to_the_gate_but_prefixed_for_everything_else(monkeypatch):
    """/monitor/estate validates its own key, so the gate must let it through; any FUTURE
    /monitor/* route must be authed by default rather than falling through the default-open
    hole that shipped /campaigns and /disposition unauthenticated."""
    core = _core(monkeypatch)
    assert "/monitor/estate" in core.ALWAYS_PUBLIC
    assert "/monitor" in core.API_PREFIXES
    assert core.is_public("/monitor/estate") is True
    assert core.is_public("/monitor/anything-added-later") is False


def test_deploy_script_stamps_the_production_flag():
    """deploy.sh only ever ships the public demo, so it must mark the app as production —
    under ACP_DEPLOY_ENV, not ACP_ENV (that name is the ACA environment name in this script)."""
    sh = (ACP / "deploy" / "public" / "deploy.sh").read_text()
    assert 'DEPLOY_ENV_ENV="ACP_DEPLOY_ENV=production"' in sh
    assert sh.count("$DEPLOY_ENV_ENV") >= 2          # wired into both update and create
