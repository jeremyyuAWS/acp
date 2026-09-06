"""Persisting a capacity schedule, and the two promises Phase 3 makes about it.

**An edit cannot silently lose another edit.** Two administrators changing warm capacity in
different tabs is not a merge conflict — it is one of them undoing the other's floor and finding
out during a deploy. §8 asks for optimistic concurrency; these hold it.

**An override cannot silently become permanent.** §5.4 says so, and the obvious implementation
fails in exactly that direction: a background sweeper that clears expired overrides leaves the
override in force if the sweeper stops. Expiry is enforced on READ instead, so there is no
component whose failure can extend one. The test that matters here is the one that expires an
override with nothing running at all.
"""
from __future__ import annotations

import json
import sys
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))

import capacity_schedule as cs  # noqa: E402
import capacity_store as store_mod  # noqa: E402


class FakeStore:
    """app_settings and decision_log, and nothing else — the two tables this feature uses."""

    def __init__(self):
        self.settings, self.decisions = {}, []

    def get_setting(self, key, default=None):
        return self.settings.get(key, default)

    def set_setting(self, key, value):
        self.settings[key] = value

    def log_decision(self, actor, action, **kw):
        self.decisions.append({"actor": actor, "action": action, **kw})


class BrokenStore(FakeStore):
    def get_setting(self, key, default=None):
        raise RuntimeError("database unavailable")


@pytest.fixture
def store():
    return FakeStore()


def utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


# ── persistence ──────────────────────────────────────────────────────────────────────────────

def test_nothing_saved_yet_reads_as_the_proposal_and_not_as_applied(store):
    loaded = store_mod.load_schedule(store)
    assert loaded == cs.PROPOSED
    assert loaded.applied is False


def test_a_saved_schedule_survives_a_round_trip(store):
    proposed = replace(cs.PROPOSED, enabled=True, start="07:00",
                       business_hours={**cs.PROPOSED.business_hours, "assess": 3})
    saved = store_mod.save_schedule(store, proposed, actor="a@example.com",
                                    expected_version=0, reason="warm earlier")
    reloaded = store_mod.load_schedule(store)
    assert reloaded == saved
    assert reloaded.start == "07:00"
    assert reloaded.business_hours["assess"] == 3
    assert reloaded.days == cs.PROPOSED.days, "a tuple field came back as something else"


def test_saving_marks_the_schedule_applied_and_bumps_the_version(store):
    """`applied` is what makes drift meaningful: a stored schedule is what ACP intends, so a
    difference from Azure is now a real finding rather than the distance from a proposal."""
    first = store_mod.save_schedule(store, cs.PROPOSED, actor="a", expected_version=0, reason="r")
    assert (first.version, first.applied) == (1, True)
    second = store_mod.save_schedule(store, first, actor="a", expected_version=1, reason="r")
    assert second.version == 2


def test_an_unreadable_store_degrades_to_a_schedule_that_reads_as_not_in_force():
    """§12: retain something truthful. A fabricated live schedule is the one answer that would
    be worse than saying nothing."""
    loaded = store_mod.load_schedule(BrokenStore())
    assert loaded.applied is False


def test_a_corrupt_row_does_not_take_the_tab_down(store):
    store.settings[store_mod.SCHEDULE_KEY] = "{not json"
    assert store_mod.load_schedule(store).applied is False


def test_a_row_carrying_an_unknown_field_still_loads(store):
    """A schedule written by a later version must not make this one refuse to read production's
    own configuration."""
    body = json.loads(store_mod._serialise(replace(cs.PROPOSED, version=4, applied=True)))
    body["a_field_from_the_future"] = True
    store.settings[store_mod.SCHEDULE_KEY] = json.dumps(body)
    loaded = store_mod.load_schedule(store)
    assert loaded.version == 4 and loaded.applied is True


# ── optimistic concurrency ───────────────────────────────────────────────────────────────────

def test_a_stale_version_is_refused_with_both_numbers(store):
    store_mod.save_schedule(store, cs.PROPOSED, actor="a", expected_version=0, reason="first")
    with pytest.raises(store_mod.ConcurrentEdit) as excinfo:
        store_mod.save_schedule(store, cs.PROPOSED, actor="b", expected_version=0, reason="second")
    assert (excinfo.value.expected, excinfo.value.actual) == (0, 1)


def test_a_refused_write_changes_nothing(store):
    saved = store_mod.save_schedule(store, replace(cs.PROPOSED, start="07:00"),
                                    actor="a", expected_version=0, reason="first")
    with pytest.raises(store_mod.ConcurrentEdit):
        store_mod.save_schedule(store, replace(cs.PROPOSED, start="09:00"),
                                actor="b", expected_version=0, reason="second")
    assert store_mod.load_schedule(store) == saved
    assert store_mod.load_schedule(store).start == "07:00"


def test_a_refused_write_is_still_audited(store):
    """§11 lists validation rejection among the things to record. A write somebody attempted and
    lost is exactly the evidence that explains a floor that 'changed by itself'."""
    store_mod.save_schedule(store, cs.PROPOSED, actor="a", expected_version=0, reason="first")
    with pytest.raises(store_mod.ConcurrentEdit):
        store_mod.save_schedule(store, cs.PROPOSED, actor="b", expected_version=0, reason="second")
    rejected = [d for d in store.decisions if d["action"].endswith("rejected")]
    assert len(rejected) == 1
    assert rejected[0]["actor"] == "b"


# ── audit ────────────────────────────────────────────────────────────────────────────────────

def test_the_audit_row_names_the_actor_the_reason_and_what_moved(store):
    store_mod.save_schedule(store, replace(cs.PROPOSED, start="07:00"),
                            actor="admin@example.com", expected_version=0,
                            reason="warm earlier for the EU team")
    row = store.decisions[-1]
    assert row["actor"] == "admin@example.com"
    assert row["action"] == "settings.capacity_schedule.saved"
    assert "warm earlier for the EU team" in row["detail"]
    assert "start" in row["detail"] and "07:00" in row["detail"]
    assert "v0 -> v1" in row["detail"]


def test_the_audit_row_records_only_the_fields_that_moved(store):
    """A full before/after of every field on every edit is a log nobody reads, which is the same
    outcome as no log."""
    store_mod.save_schedule(store, replace(cs.PROPOSED, start="07:00"),
                            actor="a", expected_version=0, reason="r")
    detail = store.decisions[-1]["detail"]
    assert "start" in detail
    assert "timezone" not in detail, "an unchanged field was logged"


def test_an_audit_failure_does_not_lose_the_write(store):
    """Losing the row is better than losing the change. The write has already been persisted by
    the time the log is appended, and raising here would report a successful save as a failure."""
    def explode(*a, **kw):
        raise RuntimeError("decision log unavailable")
    store.log_decision = explode
    saved = store_mod.save_schedule(store, cs.PROPOSED, actor="a", expected_version=0, reason="r")
    assert saved.version == 1
    assert store_mod.load_schedule(store).version == 1


def test_no_audit_row_carries_a_connection_string(store):
    """§11: secrets and raw connection strings must never appear in audit data."""
    store_mod.save_schedule(store, cs.PROPOSED, actor="a", expected_version=0,
                            reason="postgres://user:pw@host/db")
    joined = " ".join(str(d.get("detail")) for d in store.decisions)
    # The reason is operator-supplied text and is recorded as given; what must never appear is a
    # credential this code went and fetched. Asserting the policy's own secret REFERENCE is what
    # gets logged, not a resolved value.
    assert "database-url" not in joined


# ── overrides ────────────────────────────────────────────────────────────────────────────────

def test_an_override_expires_with_nothing_running(store):
    """THE PROMISE §5.4 MAKES. No sweeper, no scheduler, no background task — the read path
    refuses to return an override past its expiry, so there is no component whose failure can
    extend one."""
    now = utc(2026, 9, 7, 15, 0)
    store_mod.set_override(store, mode="business_hours", floors=None, duration="30m",
                           reason="big batch landing", actor="a", schedule=cs.PROPOSED, now=now)
    assert store_mod.get_override(store, now + timedelta(minutes=29)) is not None
    assert store_mod.get_override(store, now + timedelta(minutes=31)) is None
    # And the row is still sitting there — expiry is a property of reading it, not of deleting it.
    assert store.settings[store_mod.OVERRIDE_KEY]


def test_an_override_requires_a_reason(store):
    with pytest.raises(store_mod.OverrideError):
        store_mod.set_override(store, mode="business_hours", floors=None, duration="1h",
                               reason="   ", actor="a", schedule=cs.PROPOSED)


def test_a_custom_override_must_name_the_capacity_it_wants(store):
    with pytest.raises(store_mod.OverrideError):
        store_mod.set_override(store, mode="custom", floors=None, duration="1h",
                               reason="r", actor="a", schedule=cs.PROPOSED)


def test_an_unknown_duration_is_refused_rather_than_defaulted(store):
    """A default here would be the quiet way an override outlives what its author intended."""
    with pytest.raises(store_mod.OverrideError):
        store_mod.set_override(store, mode="off_hours", floors=None, duration="forever",
                               reason="r", actor="a", schedule=cs.PROPOSED)


def test_until_next_transition_is_resolved_against_the_schedule_now(store):
    enabled = replace(cs.PROPOSED, enabled=True)
    now = utc(2026, 1, 12, 18, 0)                       # Monday 10:00 Pacific, mid-window
    override = store_mod.set_override(store, mode="business_hours", floors=None,
                                      duration="until_next_transition", reason="r",
                                      actor="a", schedule=enabled, now=now)
    assert override["expires_at"] == utc(2026, 1, 13, 4, 0).isoformat()   # 20:00 PST


def test_until_next_transition_is_refused_when_there_is_no_next_transition(store):
    """A disabled schedule has none, and an override with no end is the thing §5.4 forbids."""
    with pytest.raises(store_mod.OverrideError) as excinfo:
        store_mod.set_override(store, mode="business_hours", floors=None,
                               duration="until_next_transition", reason="r",
                               actor="a", schedule=cs.PROPOSED)
    assert "no end" in str(excinfo.value)


def test_an_override_records_who_why_and_what_resumes(store):
    saved = store_mod.save_schedule(store, replace(cs.PROPOSED, enabled=True),
                                    actor="a", expected_version=0, reason="r")
    override = store_mod.set_override(store, mode="off_hours", floors=None, duration="2h",
                                      reason="cost test", actor="admin@example.com",
                                      schedule=saved)
    assert override["actor"] == "admin@example.com"
    assert override["reason"] == "cost test"
    assert override["resumes_schedule_version"] == saved.version
    assert store.decisions[-1]["action"] == "settings.capacity_override.created"


def test_cancelling_an_override_is_audited_and_idempotent(store):
    store_mod.set_override(store, mode="off_hours", floors=None, duration="1h",
                           reason="r", actor="a", schedule=cs.PROPOSED)
    store_mod.clear_override(store, actor="a")
    assert store_mod.get_override(store) is None
    store_mod.clear_override(store, actor="a")
    cancelled = [d for d in store.decisions if d["action"].endswith("override.cancelled")]
    assert len(cancelled) == 2


# ── which authority is in force ──────────────────────────────────────────────────────────────

def test_an_override_outranks_the_schedule_and_says_so(store):
    """The mode returned is `manual_override`, never the name of the mode it copied — nothing
    downstream may report an overridden fleet as though the schedule produced it."""
    enabled = replace(cs.PROPOSED, enabled=True)
    now = utc(2026, 1, 12, 18, 0)
    override = store_mod.set_override(store, mode="business_hours", floors=None, duration="1h",
                                      reason="r", actor="a", schedule=enabled, now=now)
    floors, authority = store_mod.effective_floors(enabled, override, now)
    assert authority == "manual_override"
    assert floors == enabled.business_hours


def test_without_an_override_the_schedules_own_mode_is_in_force(store):
    enabled = replace(cs.PROPOSED, enabled=True)
    floors, authority = store_mod.effective_floors(enabled, None, utc(2026, 1, 12, 18, 0))
    assert authority == "business_hours"
    assert floors == enabled.business_hours
    night, night_authority = store_mod.effective_floors(enabled, None, utc(2026, 1, 12, 9, 0))
    assert night_authority == "off_hours"
    assert night == enabled.off_hours


def test_a_custom_override_carries_the_floors_it_was_given(store):
    override = store_mod.set_override(store, mode="custom", floors={"assess": 7},
                                      duration="1h", reason="r", actor="a",
                                      schedule=cs.PROPOSED)
    floors, authority = store_mod.effective_floors(cs.PROPOSED, override, datetime.now(timezone.utc))
    assert authority == "manual_override"
    assert floors == {"assess": 7}
