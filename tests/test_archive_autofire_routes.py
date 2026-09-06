"""The archive auto-fire API: what each route refuses, and to whom.

THE GATES ARE THE FEATURE HERE. Every other test module in this set asks whether the decision is
right; these ask whether the wrong person can reach it at all, and whether one tenant's call can
touch another tenant's estate. The route functions are called directly against a real store —
the same harness tests/test_second_opinion_policy_route.py uses — because what is under test is
the function's own gating and scoping, not FastAPI's ability to route a path.
"""
import types
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

OWNER = "owner@example.com"
OTHER = "other@example.com"


def _request(email=OWNER, token="sp-token"):
    return types.SimpleNamespace(
        state=types.SimpleNamespace(user_email=email),
        headers={"x-sp-token": token} if token else {})


@pytest.fixture()
def routes(isolated_store, monkeypatch):
    from routes import lifecycle_archive
    monkeypatch.setattr(lifecycle_archive.core, "store", isolated_store)
    monkeypatch.setattr(lifecycle_archive, "_require_admin", lambda _r: None)
    monkeypatch.setattr(lifecycle_archive, "_require_owner", lambda _r: None)
    return lifecycle_archive


def _enabled_body(routes, **over):
    body = {"enabled": True, "dry_run": True, "archive_root": "Archive",
            "source_connections": ["sharepoint:d1"], "rule_ids": ["r1"],
            "required_evidence": ["metadata_link"]}
    body.update(over)
    return routes.ArchivePolicyIn(**body)


# ── Defaults ─────────────────────────────────────────────────────────────────

def test_a_tenant_that_never_configured_this_reads_as_unconfigured_and_disabled(routes):
    result = routes.get_archive_policy(_request())
    assert result["configured"] is False
    assert result["policy"]["enabled"] is False and result["policy"]["dry_run"] is True
    assert "never authorize an automatic move" in result["notice"]


def test_the_api_states_the_safety_principle_rather_than_leaving_it_to_the_ui(routes):
    """An integrator reading this response is owed the same guarantee the screen gives a person."""
    assert "Age, filename similarity and inactivity" in routes.get_archive_policy(_request())["notice"]


# ── Policy writes ────────────────────────────────────────────────────────────

def test_enabling_without_a_destination_is_refused_and_nothing_is_stored(routes):
    with pytest.raises(HTTPException) as exc:
        routes.put_archive_policy(_enabled_body(routes, archive_root=""), _request())
    assert exc.value.status_code == 400 and "archive destination" in exc.value.detail
    assert routes.get_archive_policy(_request())["configured"] is False


def test_a_partial_update_merges_rather_than_clearing_what_it_omits(routes):
    routes.put_archive_policy(_enabled_body(routes), _request())
    after = routes.put_archive_policy(routes.ArchivePolicyIn(dry_run=False), _request())
    assert after["policy"]["dry_run"] is False
    assert after["policy"]["archive_root"] == "Archive"
    assert after["policy"]["rule_ids"] == ["r1"]


def test_the_snapshot_is_recorded_on_a_policy_write_not_only_on_a_run(routes, isolated_store):
    result = routes.put_archive_policy(_enabled_body(routes), _request())
    assert isolated_store.get_archive_snapshot(result["snapshot_id"], OWNER) is not None


def test_writing_a_policy_requires_admin(routes, monkeypatch):
    def refuse(_r):
        raise HTTPException(403, "admin access required")
    monkeypatch.setattr(routes, "_require_admin", refuse)
    with pytest.raises(HTTPException) as exc:
        routes.put_archive_policy(_enabled_body(routes), _request())
    assert exc.value.status_code == 403


def test_running_requires_owner_not_merely_admin(routes, monkeypatch):
    def refuse(_r):
        raise HTTPException(403, "owner access required")
    monkeypatch.setattr(routes, "_require_owner", refuse)
    with pytest.raises(HTTPException) as exc:
        routes.run_archive(_request(), scan_id="s1")
    assert exc.value.status_code == 403


# ── Kill switch ──────────────────────────────────────────────────────────────

def test_the_kill_switch_is_its_own_route_and_does_not_revalidate_the_rest(routes):
    """An operator reaching for the switch is having a bad day already: it must not fail on an
    unrelated validation error elsewhere in the policy."""
    routes.put_archive_policy(_enabled_body(routes), _request())
    # Make the stored policy one that `policy_problem` would now refuse to ENABLE.
    routes.put_archive_policy(routes.ArchivePolicyIn(enabled=False, rule_ids=[]), _request())
    result = routes.set_kill_switch(routes.KillSwitchIn(on=True), _request())
    assert result["policy"]["kill_switch"] is True


def test_the_kill_switch_is_stored_where_the_run_loop_reads_it(routes, isolated_store):
    import archive_execution
    routes.set_kill_switch(routes.KillSwitchIn(on=True), _request())
    assert archive_execution.load_policy(isolated_store, OWNER)["kill_switch"] is True
    routes.set_kill_switch(routes.KillSwitchIn(on=False), _request())
    assert archive_execution.load_policy(isolated_store, OWNER)["kill_switch"] is False


# ── Tenancy ──────────────────────────────────────────────────────────────────

def test_one_tenants_policy_is_invisible_to_another(routes):
    routes.put_archive_policy(_enabled_body(routes), _request())
    theirs = routes.get_archive_policy(_request(OTHER))
    assert theirs["configured"] is False
    assert theirs["policy"]["archive_root"] == ""


def test_candidates_for_an_unknown_or_other_tenant_scan_are_empty_not_a_404(routes):
    """Empty rather than 404 on purpose: a 404-vs-200 difference would let a caller enumerate
    which scan ids exist in other tenants."""
    assert routes.list_candidates(_request(OTHER), scan_id="s-does-not-exist")["items"] == []


def test_an_execution_belonging_to_another_tenant_is_a_404(routes, isolated_store):
    isolated_store.claim_archive_execution(
        idempotency_key="k1", execution_id="e1", owner_email=OWNER, scan_id="s1",
        file="a.docx", policy_id="r1", snapshot_id="snap", source_connection="sharepoint:d1",
        source_item_id="i1", source_drive_id="d1", source_etag=None, source_path="a.docx",
        replacement_item_id="i2", replacement_path="b.docx", evidence_json="[]",
        destination_path="Archive/a.docx", actor=OWNER, dry_run=False)
    assert routes.get_execution("e1", _request())["execution_id"] == "e1"
    with pytest.raises(HTTPException) as exc:
        routes.get_execution("e1", _request(OTHER))
    assert exc.value.status_code == 404
    # Arguments spelled out because these functions are called directly here: FastAPI would
    # resolve the Query() defaults, and a bare call passes the marker objects themselves.
    assert routes.list_executions(_request(OTHER), scan_id=None, limit=200)["executions"] == []
    assert len(routes.list_executions(_request(), scan_id=None, limit=200)["executions"]) == 1


# ── The audit view ───────────────────────────────────────────────────────────

def test_an_execution_resolves_its_policy_snapshot_rather_than_returning_a_bare_hash(routes,
                                                                                     isolated_store):
    import archive_autofire as af
    policy = af.normalize_policy({"enabled": True, "archive_root": "Archive",
                                  "source_connections": ["sharepoint:d1"], "rule_ids": ["r1"]})
    snapshot = af.policy_snapshot(policy)
    isolated_store.save_archive_snapshot(snapshot["snapshot_id"], OWNER, snapshot["policy"])
    isolated_store.claim_archive_execution(
        idempotency_key="k2", execution_id="e2", owner_email=OWNER, scan_id="s1",
        file="a.docx", policy_id="r1", snapshot_id=snapshot["snapshot_id"],
        source_connection="sharepoint:d1", source_item_id="i1", source_drive_id="d1",
        source_etag=None, source_path="a.docx", replacement_item_id="i2",
        replacement_path="b.docx", evidence_json='[{"type": "metadata_link"}]',
        destination_path="Archive/a.docx", actor=OWNER, dry_run=False)
    row = routes.get_execution("e2", _request())
    assert row["policy_snapshot"]["archive_root"] == "Archive"
    assert row["evidence"][0]["type"] == "metadata_link"
    assert row["state_label"]


def test_a_run_without_a_graph_credential_moves_nothing_and_says_so(routes, isolated_store):
    """No `x-sp-token` on the request. Every eligible item gets a truthful blocked row rather than
    the run failing, because one unreachable connection must not abandon the whole queue."""
    routes.put_archive_policy(_enabled_body(routes, dry_run=False), _request())
    report = routes.run_archive(_request(token=None), scan_id="s-none")
    assert report["completed"] == 0 and report["eligible"] == 0
