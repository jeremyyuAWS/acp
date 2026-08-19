"""The per-user isolation invariant is announced correctly (backlog R13).

`app._announce_isolation_mode` is the one place the deployment says out loud whether per-user data
isolation is ON. The behaviour was implemented but never tested, and it guards a PHI-grade property:
with isolation OFF every signed-in user shares the single 'demo' estate and can read everyone else's
scans and remediated files. The footgun the warning exists to catch is silent — ACCESS_CODE and
GOOGLE_CLIENT_ID are an if/ELIF, so setting an access code on a deployment that already has Google
configured does not add a second factor; it stops the user email being stamped and turns isolation
off as a side effect.

These pin the invariant `isolated == bool(GOOGLE_CLIENT_ID) and not ACCESS_CODE` through the real
function's own output, so the announcement can never quietly say ON while the gate shares one estate.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))


def _announce(monkeypatch, *, google, access_code, is_prod=False):
    """Run the real _announce_isolation_mode under a chosen config."""
    import core
    from app import _announce_isolation_mode
    monkeypatch.setattr(core, "GOOGLE_CLIENT_ID", google, raising=False)
    monkeypatch.setattr(core, "ACCESS_CODE", access_code, raising=False)
    monkeypatch.setattr(core, "IS_PROD", is_prod, raising=False)
    _announce_isolation_mode()


def test_isolation_is_on_only_with_google_and_no_access_code(monkeypatch, capsys):
    _announce(monkeypatch, google="client-abc.apps.googleusercontent.com", access_code=None)
    out = capsys.readouterr().out
    assert "per-user data isolation: ON" in out
    assert "OFF" not in out


def test_an_access_code_on_a_google_deploy_turns_isolation_off(monkeypatch, capsys):
    # THE invariant: the if/ELIF footgun. Google IS configured, but an access code is also set, so
    # the gate never stamps a user email — isolation is off, and the reason names the access code.
    _announce(monkeypatch, google="client-abc.apps.googleusercontent.com", access_code="s3cret")
    out = capsys.readouterr().out
    assert "per-user data isolation is OFF" in out
    assert "ACP_ACCESS_CODE is set" in out           # names the specific cause, not just "off"
    assert "NOT safe for multi-user or PHI data" in out


def test_no_google_configured_is_off_for_the_other_reason(monkeypatch, capsys):
    _announce(monkeypatch, google=None, access_code=None)
    out = capsys.readouterr().out
    assert "per-user data isolation is OFF" in out
    assert "no ACP_GOOGLE_CLIENT_ID" in out


def test_isolation_off_in_production_is_flagged_as_production(monkeypatch, capsys):
    # The loudest case: shared estate on a production deployment gets the PRODUCTION marker.
    _announce(monkeypatch, google="client-abc.apps.googleusercontent.com", access_code="s3cret",
              is_prod=True)
    out = capsys.readouterr().out
    assert "per-user data isolation is OFF" in out
    assert "PRODUCTION." in out
