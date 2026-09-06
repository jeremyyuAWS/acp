"""The read-only Scheduling endpoints — Phase 2 of docs/prd-capacity-scheduling.md.

Two things these hold that the pure-logic tests cannot:

  * the ADMIN SPLIT. GET is open (PRD §4 gives view-only Settings users the right to inspect the
    schedule, and §10 puts the validation result on that same surface); POST /validate is
    admin-gated because it takes a body and is the dry run that precedes Phase 3's write.
  * the HONESTY FIELDS. `applied: false` and `drift_evaluated: false` are what stop a proposal
    nobody has put into force from reading like a live schedule — the same class of quiet
    wrongness as a panel of dashes reporting `configured: true`.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))

import capacity_schedule as cs  # noqa: E402
from routes import control  # noqa: E402


class _Req:
    """Minimal stand-in for the Request _require_admin reads."""

    def __init__(self, email=""):
        self.state = type("S", (), {"user_email": email})()


@pytest.fixture(autouse=True)
def _no_azure(monkeypatch):
    """Every test here runs with Azure unconfigured unless it says otherwise, so nothing reaches
    a real subscription and the unconfigured path — the one a fresh deployment hits — is the
    default rather than an afterthought."""
    monkeypatch.setattr(control, "_AZ_CONFIGURED", False)


def test_the_schedule_reads_as_proposed_not_as_applied():
    payload = control.get_capacity_schedule()
    assert payload["applied"] is False
    assert payload["drift_evaluated"] is False
    assert payload["drift"] == []
    assert payload["version"] == 0


def test_the_payload_carries_the_prd_shape():
    payload = control.get_capacity_schedule()
    assert payload["timezone"] == "America/Los_Angeles"
    assert payload["days"] == ["mon", "tue", "wed", "thu", "fri"]
    assert (payload["start"], payload["end"]) == ("06:00", "20:00")
    assert payload["business_hours"]["assess"] == 5
    assert payload["maximums"]["remediate"] == 10
    assert payload["effective_mode"] in ("business_hours", "off_hours")


def test_a_disabled_schedule_reports_no_next_transition_rather_than_a_wrong_one():
    """PROPOSED ships disabled, so the honest answer is None. A fabricated next transition would
    be the most quietly wrong field on the whole tab."""
    payload = control.get_capacity_schedule()
    assert payload["enabled"] is False
    assert payload["next_transition_at"] is None
    assert payload["next_transition_to"] is None


def test_the_get_carries_the_validation_a_view_only_user_is_entitled_to():
    """§10 lists 'validation result' among what Settings shows, and §4 lets a view-only user see
    it. Locking every validation behind the admin-only POST would make that impossible."""
    payload = control.get_capacity_schedule()
    validation = payload["validation"]
    assert validation["blocked"] is True, "the PRD's own table is over budget — see finding R2"
    assert any(f["code"] == "over_connection_budget" for f in validation["findings"])
    assert validation["capacity"]["connection_headroom"] < 0


def test_an_unconfigured_azure_reports_scalers_as_not_configured_never_as_healthy():
    payload = control.get_capacity_schedule()
    assert payload["azure_configured"] is False
    assert payload["observed"] == {}
    assert {s["state"] for s in payload["scalers"].values()} == {"not_configured"}


def test_a_failing_azure_read_does_not_take_the_schedule_down(monkeypatch):
    """The schedule is a durable intention; Azure being unreachable must not hide it."""
    monkeypatch.setattr(control, "_AZ_CONFIGURED", True)
    monkeypatch.setattr(control, "get_capacity", lambda: (_ for _ in ()).throw(RuntimeError("azure down")))
    payload = control.get_capacity_schedule()
    assert payload["business_hours"]["assess"] == 5
    assert {s["state"] for s in payload["scalers"].values()} == {"unreadable"}


def test_observed_capacity_is_surfaced_with_its_scale_rules(monkeypatch):
    monkeypatch.setattr(control, "_AZ_CONFIGURED", True)
    monkeypatch.setattr(control, "get_capacity", lambda: {
        "configured": True,
        "apps": {
            "acp-assess": {"min_replicas": 5, "max_replicas": 5, "current_replicas": 5,
                           "scale": {"rules": [{"name": "assess-queue"}]}},
            "acp-remediate": {"min_replicas": 5, "max_replicas": 10, "current_replicas": 6,
                              "scale": {"rules": [{"name": "remediation-queue"}]}},
        },
    })
    payload = control.get_capacity_schedule()
    assert payload["observed"]["acp-assess"]["scale_rules"] == ["assess-queue"]
    assert payload["observed"]["acp-remediate"]["current_replicas"] == 6
    # AC 10, through the API: a rule on a pinned tier must not read as healthy.
    assert payload["scalers"]["assess"]["state"] == "pinned"
    assert payload["scalers"]["remediate"]["state"] == "healthy"


def test_drift_stays_empty_while_the_schedule_is_only_proposed(monkeypatch):
    """Azure differs from the proposal in every service, and NONE of it is drift: nothing has
    drifted from a schedule nobody has put into force. Reporting it would be true arithmetic and
    a false statement, and a drift indicator that is always on is one nobody reads."""
    monkeypatch.setattr(control, "_AZ_CONFIGURED", True)
    monkeypatch.setattr(control, "get_capacity", lambda: {
        "configured": True,
        "apps": {"acp-assess": {"min_replicas": 1, "max_replicas": 1}},
    })
    payload = control.get_capacity_schedule()
    assert payload["drift"] == []
    assert payload["drift_evaluated"] is False
    # Bite check: the comparison itself does find the difference when it is asked to.
    assert cs.drift(cs.PROPOSED, "business_hours",
                    {"acp-assess": {"min_replicas": 1, "max_replicas": 1}})


# ── POST /validate ───────────────────────────────────────────────────────────────────────────

def test_validate_is_admin_only(monkeypatch):
    import core
    monkeypatch.setattr(core, "OWNER_EMAIL", "owner@example.com")
    monkeypatch.setattr(core, "is_admin", lambda email: email == "owner@example.com")
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as excinfo:
        control.validate_capacity_schedule(control.ScheduleProposal(), _Req("someone@example.com"))
    assert excinfo.value.status_code == 403

    allowed = control.validate_capacity_schedule(control.ScheduleProposal(), _Req("owner@example.com"))
    assert "findings" in allowed


def test_validate_patches_only_the_fields_supplied():
    """"What would raising the assess ceiling cost?" must be one field, not a restatement."""
    result = control.validate_capacity_schedule(
        control.ScheduleProposal(maximums={**cs.PROPOSED.maximums, "assess": 5}), _Req())
    assert result["proposed"]["maximums"]["assess"] == 5
    assert result["proposed"]["start"] == "06:00", "an unsupplied field was not carried through"
    assert result["proposed"]["business_hours"] == dict(cs.PROPOSED.business_hours)


def test_validate_saves_nothing():
    """The whole phase in one assertion: pricing a schedule must not become the schedule."""
    before = control.get_capacity_schedule()
    control.validate_capacity_schedule(
        control.ScheduleProposal(enabled=True, maximums={"web": 3, "discovery": 4,
                                                         "assess": 99, "remediate": 10}), _Req())
    after = control.get_capacity_schedule()
    assert before["maximums"] == after["maximums"]
    assert after["enabled"] is False
    assert cs.PROPOSED.maximums["assess"] == 10


def test_validate_reports_a_shape_error_rather_than_a_500():
    """An unknown zone is a finding, not a crash — and the proposal still comes back so the
    caller can see WHICH shape produced the verdict.

    A DISABLED schedule never resolves its zone: `effective_mode` answers off-hours and
    `next_transition` answers None without asking what "Mars/Olympus_Mons" means. So the echo
    succeeds here and the finding is what carries the problem.
    """
    result = control.validate_capacity_schedule(
        control.ScheduleProposal(timezone="Mars/Olympus_Mons"), _Req())
    assert result["blocked"] is True
    assert any(f["code"] == "unknown_timezone" for f in result["findings"])
    assert result["proposed"]["timezone"] == "Mars/Olympus_Mons"


def test_an_enabled_schedule_with_an_unknown_zone_still_answers():
    """The other path: enabling it makes the time functions actually resolve the zone, which
    raises. The endpoint must report the finding rather than let a 500 hide it."""
    result = control.validate_capacity_schedule(
        control.ScheduleProposal(enabled=True, timezone="Mars/Olympus_Mons"), _Req())
    assert result["blocked"] is True
    assert any(f["code"] == "unknown_timezone" for f in result["findings"])
    assert result["proposed"] is None, (
        "an enabled schedule with an unresolvable zone has no effective mode to report")


def test_validate_finds_a_shape_that_fits():
    """The endpoint must be able to say yes, or a validator that only ever refuses teaches
    nothing about what would work. Off-hours floors with the PRD's own ceilings fit."""
    result = control.validate_capacity_schedule(control.ScheduleProposal(
        business_hours={"web": 1, "discovery": 1, "assess": 1, "remediate": 1, "gpu": 1}), _Req())
    assert result["blocked"] is False, result["findings"]
    assert result["capacity"]["connection_headroom"] >= 0


# ── Phase 3: the writes ──────────────────────────────────────────────────────────────────────
#
# These drive the handlers directly against a fake store, the same way the Phase 2 tests drive
# the reads. What they hold is the three things a capacity write can get wrong without anybody
# noticing until a deploy: it can be made by the wrong person, it can silently overwrite somebody
# else's edit, and it can save a shape the fleet cannot carry.

import json  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402

import capacity_store as store_mod  # noqa: E402


class _Store:
    def __init__(self):
        self.settings, self.decisions = {}, []

    def get_setting(self, key, default=None):
        return self.settings.get(key, default)

    def set_setting(self, key, value):
        self.settings[key] = value

    def log_decision(self, actor, action, **kw):
        self.decisions.append({"actor": actor, "action": action, **kw})


@pytest.fixture
def store(monkeypatch):
    import core
    fake = _Store()
    monkeypatch.setattr(core, "store", fake)
    return fake


@pytest.fixture
def admin(monkeypatch):
    """A configured owner, so _require_admin actually gates rather than no-opping."""
    import core
    monkeypatch.setattr(core, "OWNER_EMAIL", "owner@example.com")
    monkeypatch.setattr(core, "is_admin", lambda email: email == "owner@example.com")
    return _Req("owner@example.com")


def _fits(**over):
    """A body that passes validation: off-hours floors everywhere, the PRD's own ceilings."""
    body = {"business_hours": {"web": 1, "discovery": 1, "assess": 1, "remediate": 1, "gpu": 1},
            "version": 0, "reason": "phase 3 test"}
    body.update(over)
    return control.ScheduleWrite(**body)


def test_every_write_is_admin_only(store, admin, monkeypatch):
    from fastapi import HTTPException
    outsider = _Req("someone@example.com")
    for call in (lambda: control.put_capacity_schedule(_fits(), outsider),
                 lambda: control.create_capacity_override(
                     control.OverrideRequest(mode="off_hours", duration="1h", reason="r"), outsider),
                 lambda: control.delete_capacity_override(outsider)):
        with pytest.raises(HTTPException) as excinfo:
            call()
        assert excinfo.value.status_code == 403


def test_a_valid_write_persists_and_reads_back(store, admin):
    result = control.put_capacity_schedule(_fits(start="07:00"), admin)
    assert result["version"] == 1
    assert result["start"] == "07:00"
    assert control.get_capacity_schedule()["start"] == "07:00"
    assert store_mod.load_schedule(store).applied is True


def test_a_saved_schedule_is_not_yet_applied_to_azure(store, admin):
    """Persistence and application are separate steps with separate failure modes, and §9's drift
    reporting is built on the state between them. A payload that implied otherwise would report
    an intention as a fact."""
    result = control.put_capacity_schedule(_fits(), admin)
    assert result["azure_applied"] is False


def test_a_schedule_the_fleet_cannot_carry_is_refused_and_nothing_is_written(store, admin):
    """§7: saving is BLOCKED when the fleet would exceed the database ceiling. The PRD's own
    §5.3 table is one of the schedules this refuses — which is the point, because it is the shape
    somebody would naturally type."""
    from fastapi import HTTPException
    import capacity_schedule as cs_mod

    before = store_mod.load_schedule(store)
    with pytest.raises(HTTPException) as excinfo:
        control.put_capacity_schedule(control.ScheduleWrite(
            business_hours=dict(cs_mod.PROPOSED.business_hours),
            off_hours=dict(cs_mod.PROPOSED.off_hours),
            maximums=dict(cs_mod.PROPOSED.maximums),
            version=0, reason="the PRD's own table"), admin)
    assert excinfo.value.status_code == 422
    assert any(f["code"] == "over_connection_budget" for f in excinfo.value.detail["findings"])
    assert store_mod.load_schedule(store) == before
    # §11 lists validation rejection among the things to record.
    assert [d for d in store.decisions if d["action"].endswith("rejected")]


def test_a_stale_version_is_refused_with_both_numbers(store, admin):
    """Two administrators editing warm capacity in different tabs is not a merge conflict — it is
    one of them undoing the other's floor and finding out during a deploy."""
    from fastapi import HTTPException
    control.put_capacity_schedule(_fits(start="07:00"), admin)
    with pytest.raises(HTTPException) as excinfo:
        control.put_capacity_schedule(_fits(start="09:00"), admin)   # still version=0
    assert excinfo.value.status_code == 409
    assert excinfo.value.detail["your_version"] == 0
    assert excinfo.value.detail["current_version"] == 1
    assert control.get_capacity_schedule()["start"] == "07:00"


def test_a_write_patches_only_the_fields_supplied(store, admin):
    control.put_capacity_schedule(_fits(start="07:00"), admin)
    control.put_capacity_schedule(_fits(version=1, end="18:00"), admin)
    current = control.get_capacity_schedule()
    assert (current["start"], current["end"]) == ("07:00", "18:00")


# ── overrides through the API ────────────────────────────────────────────────────────────────

def test_an_override_takes_effect_and_says_which_authority_set_the_floors(store, admin):
    control.put_capacity_schedule(_fits(enabled=True), admin)
    control.create_capacity_override(
        control.OverrideRequest(mode="custom", duration="1h", reason="large batch landing",
                                floors={"assess": 4}), admin)
    payload = control.get_capacity_schedule()
    assert payload["effective_mode"] == "manual_override"
    assert payload["effective_floors"] == {"assess": 4}
    assert payload["override"]["reason"] == "large batch landing"
    assert payload["override"]["actor"] == "owner@example.com"


def test_an_override_without_a_reason_is_refused(store, admin):
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as excinfo:
        control.create_capacity_override(
            control.OverrideRequest(mode="off_hours", duration="1h", reason=""), admin)
    assert excinfo.value.status_code == 422


def test_an_expired_override_disappears_from_the_payload_on_its_own(store, admin):
    """No sweeper runs in this test, and that is the assertion: expiry is enforced by the read
    path, so there is no component whose failure could extend the override."""
    control.create_capacity_override(
        control.OverrideRequest(mode="off_hours", duration="30m", reason="cost test"), admin)
    assert control.get_capacity_schedule()["override"] is not None

    body = json.loads(store.settings[store_mod.OVERRIDE_KEY])
    body["expires_at"] = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    store.settings[store_mod.OVERRIDE_KEY] = json.dumps(body)

    payload = control.get_capacity_schedule()
    assert payload["override"] is None
    assert payload["effective_mode"] != "manual_override"


def test_cancelling_an_override_is_idempotent(store, admin):
    control.create_capacity_override(
        control.OverrideRequest(mode="off_hours", duration="1h", reason="r"), admin)
    assert control.delete_capacity_override(admin)["cleared"] is True
    assert control.delete_capacity_override(admin)["cleared"] is False


def test_an_override_is_not_reported_as_drift(store, admin, monkeypatch):
    """An override is a deliberate, audited divergence. Reporting it as configuration drift would
    bury the real thing among the expected ones."""
    monkeypatch.setattr(control, "_AZ_CONFIGURED", True)
    monkeypatch.setattr(control, "get_capacity", lambda: {
        "configured": True,
        "apps": {"acp-assess": {"min_replicas": 1, "max_replicas": 10}},
    })
    control.put_capacity_schedule(_fits(enabled=True, maximums={
        "web": 3, "discovery": 4, "assess": 10, "remediate": 10, "gpu": 1}), admin)
    before = control.get_capacity_schedule()["drift"]
    control.create_capacity_override(
        control.OverrideRequest(mode="custom", duration="1h", reason="r",
                                floors={"assess": 9}), admin)
    assert control.get_capacity_schedule()["drift"] == before


# ── the rendered policy ──────────────────────────────────────────────────────────────────────

def test_the_policy_view_shows_what_would_be_applied_without_applying_it(store, admin):
    # Floors chosen because they FIT: with the PRD's ceilings, web 1 / discovery 2 / assess 4 /
    # remediate 4 lands at 147 of the 150 the server has. 2/2/4/4 does not — the extra web
    # replica alone costs 16 connections, which is the finding the Scheduling review calls out.
    control.put_capacity_schedule(_fits(enabled=True, business_hours={
        "web": 1, "discovery": 2, "assess": 4, "remediate": 4, "gpu": 1}), admin)
    policy = control.get_capacity_policy()
    assess = next(a for a in policy["apps"] if a["app"] == "acp-assess")
    kinds = {r["type"] for r in assess["rules"]}
    assert kinds == {"cron", "postgresql"}
    assert policy["transitions_create_no_revision"] is True
    # Azure is unconfigured in these tests, so no command naming a placeholder subscription is
    # rendered — the kind of thing that gets pasted.
    assert policy["az_commands"] == []


# ── Phase 4: holidays and attribution through the API ────────────────────────────────────────

def test_a_saved_holiday_round_trips_and_reaches_the_policy_view(store, admin):
    control.put_capacity_schedule(_fits(enabled=True, holidays=["2026-12-25"]), admin)
    payload = control.get_capacity_schedule()
    assert payload["holidays"] == ["2026-12-25"]
    policy = control.get_capacity_policy()
    # THE HONEST FIELD. Listing the holidays without saying Azure cannot observe them would be
    # the most expensive quiet wrongness here: an operator would believe capacity drops on the
    # day, and the bill would say otherwise.
    assert policy["holidays"]["declared"] == ["2026-12-25"]
    assert policy["holidays"]["enforced_by_policy"] is False
    assert "cron rule cannot express" in policy["holidays"]["reason"]


def test_a_schedule_without_holidays_reports_them_as_enforceable(store, admin):
    control.put_capacity_schedule(_fits(enabled=True), admin)
    assert control.get_capacity_policy()["holidays"]["enforced_by_policy"] is True


def test_an_unparseable_holiday_cannot_be_saved(store, admin):
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as excinfo:
        control.put_capacity_schedule(_fits(holidays=["christmas"]), admin)
    assert excinfo.value.status_code == 422
    assert "unparseable_holiday" in str(excinfo.value.detail)


def test_the_payload_attributes_each_service(store, admin, monkeypatch):
    monkeypatch.setattr(control, "_AZ_CONFIGURED", True)
    monkeypatch.setattr(control, "get_capacity", lambda: {
        "configured": True,
        "apps": {
            "acp-assess": {"current_replicas": 8, "min_replicas": 1, "max_replicas": 10},
            "acp-remediate": {"current_replicas": 5, "min_replicas": 1, "max_replicas": 10,
                              "draining_replicas": 2},
        },
    })
    control.put_capacity_schedule(_fits(enabled=True), admin)
    attribution = control.get_capacity_schedule()["attribution"]
    assert attribution["assess"]["reason"] in ("queue", "scheduled", "below_floor")
    assert attribution["remediate"]["reason"] == "deployment"
    assert attribution["gpu"]["reason"] == "unknown"


def test_an_override_is_named_as_the_reason_capacity_is_where_it_is(store, admin, monkeypatch):
    monkeypatch.setattr(control, "_AZ_CONFIGURED", True)
    monkeypatch.setattr(control, "get_capacity", lambda: {
        "configured": True, "apps": {"acp-assess": {"current_replicas": 9}}})
    control.put_capacity_schedule(_fits(enabled=True), admin)
    control.create_capacity_override(
        control.OverrideRequest(mode="custom", duration="1h", reason="batch",
                                floors={"assess": 9}), admin)
    assert control.get_capacity_schedule()["attribution"]["assess"]["reason"] == "manual_override"
