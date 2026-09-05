"""Tier 4's second half: Container Apps system logs, from Log Analytics.

WHAT THIS ANSWERS THAT NOTHING ELSE CAN. Metrics say a revision has no replicas; the activity log
says a write failed. Neither says WHY — image-pull errors, failed volume mounts and container
crash output are written to ContainerAppSystemLogs_CL and nowhere else.

TWO THINGS THE TESTS EXIST TO HOLD. It is OFF without a workspace, and says so with the knob to
set — the Deployments panel names this gap, and a reader that silently returned nothing would turn
a named gap into an unexplained blank. And it is NEVER LIVE: Log Analytics ingestion for Container
Apps lags two to three minutes, so every row carries that delay in the payload, because rendering
a three-minute-old log line beside a two-second event stream as equal freshness is exactly what
the provenance labels exist to prevent.
"""
from __future__ import annotations

import sys
from pathlib import Path

ACP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ACP / "api"))

import pytest

import routes.control as control


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv(control._LOG_WORKSPACE_ENV, raising=False)
    import swallowed as _s
    _s.reset()
    yield
    _s.reset()


# ── Off by default, and it says so ──────────────────────────────────────────────────────────────

def test_without_a_workspace_it_is_off_and_names_the_knob():
    block = control._system_logs("acp-assess")
    assert block["available"] is False
    assert block["configured"] is False
    assert control._LOG_WORKSPACE_ENV in block["reason"]
    assert block["rows"] == []


def test_the_off_state_still_carries_the_delay_so_nobody_expects_live_logs():
    """The caveat belongs to the feature, not to a successful query. An operator deciding whether
    to provision a workspace needs to know what they will get."""
    block = control._system_logs("acp-assess")
    assert block["ingestion_delay_s"] == 180
    assert "three minutes" in block["reason"]
    assert "never live" in block["reason"].lower()


def test_a_missing_app_name_asks_nothing(monkeypatch):
    monkeypatch.setenv(control._LOG_WORKSPACE_ENV, "ws-123")
    block = control._system_logs(None)
    assert block["available"] is False
    assert "nothing to query" in block["reason"]


# ── The revision name never reaches the query unchecked ─────────────────────────────────────────

def test_a_legal_revision_name_is_accepted():
    for name in ("acp-assess--v25", "a", "acp-assess--rev-1"):
        assert control._safe_revision(name) == name.lower()


def test_a_revision_name_that_is_not_one_is_refused():
    """Validated rather than escaped. The set of legal Container Apps revision names is small and
    well defined, so anything outside it is far likelier to be a shape change or an injection
    attempt than a name worth querying for."""
    for bad in ('acp" or 1==1 //', "acp/../etc", "acp assess", "-leading", "trailing-",
                "UPPER!", "", None, "x" * 70):
        assert control._safe_revision(bad) is None, bad


def test_an_unusable_revision_name_stops_the_query_rather_than_widening_it(monkeypatch):
    """Falling back to querying the whole app would label another revision's failures as this
    one's — the same class of error as charting one container app's CPU on another."""
    monkeypatch.setenv(control._LOG_WORKSPACE_ENV, "ws-123")
    block = control._system_logs("acp-assess", 'evil" | project 1')
    assert block["available"] is False
    assert "not in the expected format" in block["reason"]


def test_the_pattern_rejects_the_characters_kql_would_act_on():
    for ch in ('"', "'", "|", ";", "(", ")", "\\n", " ", "\\t"):
        assert control._safe_revision(f"acp{ch}rev") is None, ch


# ── Degrading honestly ──────────────────────────────────────────────────────────────────────────

def test_a_workspace_that_cannot_be_reached_is_reported_not_crashed(monkeypatch):
    """With a workspace id set but no reachable workspace behind it — no credential, a wrong id, a
    missing Log Analytics Reader grant — this must read as a named gap rather than an empty log.
    An empty log says "nothing went wrong"; that is the claim the panel must not make by accident.

    Covers the missing-package path too: azure-monitor-query is declared in api/requirements.txt,
    but an install without it takes the same route to the same honest answer.
    """
    monkeypatch.setenv(control._LOG_WORKSPACE_ENV, "ws-123")
    block = control._system_logs("acp-assess")
    assert block["available"] is False
    assert block["reason"]
    assert block["rows"] == []
    # `configured` stays TRUE: the operator did set the workspace, and "configured but failing" is
    # a different problem from "not configured" with a different fix.
    assert block["configured"] is True


def test_the_message_is_bounded():
    """A container can log a megabyte in one line, and this response is polled by the live map."""
    assert control._truncate("x" * 5000).endswith("…")
    assert len(control._truncate("x" * 5000)) == control._LOG_MESSAGE_MAX + 1
    assert control._truncate("short") == "short"
    assert control._truncate(None) is None
    assert control._truncate("   ") is None


# ── It reaches the payload ──────────────────────────────────────────────────────────────────────

def test_the_deployments_block_carries_the_system_log_state(monkeypatch):
    """The panel already names this gap; the reader is what closes it. If the two disagreed, the
    panel would keep saying "not configured" after a workspace was provisioned."""
    monkeypatch.setattr(control, "_AZ_CONFIGURED", False)
    payload = control.get_capacity()
    logs = payload["deployments"]["system_logs"]
    assert logs["available"] is False
    assert logs["configured"] is False
    assert control._LOG_WORKSPACE_ENV in logs["reason"]


def test_the_configured_flag_follows_the_environment(monkeypatch):
    """"Configured but failing" and "not configured" are different problems with different fixes,
    and an operator who has just set the workspace needs to see the first one."""
    assert control._empty_system_logs()["configured"] is False
    monkeypatch.setenv(control._LOG_WORKSPACE_ENV, "ws-123")
    assert control._empty_system_logs()["configured"] is True
