"""When a Discover run's inventory was taken (ADR 0020).

An inventory is a snapshot: every count taken from it is true only as of the instant discovery
finished. Before `scan_runs.discovered_at` there was no such instant at the run grain —
`completed_at` is written at ASSESS finalize and stays NULL on a Discover-only run (which is why
`previous_run_for_source` already works around it with COALESCE), and `started_at` is when the
listing BEGAN and is written even for a run that then died mid-listing.

These pin the stamp, its set-once contract, the derivation for runs that predate the column, and
the fact that discovery still succeeds when the stamp cannot be written.
"""
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))


@pytest.fixture()
def st(monkeypatch):
    import store as store_mod
    monkeypatch.setattr(store_mod, "_SQLITE_PATH", Path(tempfile.mkdtemp()) / "discat.db")
    return store_mod.Store()


def _discovered_run(st, sid="s1", started="2026-08-19T09:00:00+00:00"):
    """A run in exactly the state ADR 0020 leaves it in: listed, inventoried, NOT assessed."""
    st.init_scan_run(sid, "drive", 2, started, "acp", "hash1", owner="dana@x.com",
                     status="discovered")
    st.add_inventory(sid, [
        {"file": "a.docx", "doc_class": "document", "discovered_at": "2026-08-19T10:00:00+00:00"},
        {"file": "b.pdf", "doc_class": "document", "discovered_at": "2026-08-19T10:04:00+00:00"},
    ])
    return sid


# ── the stamp itself ─────────────────────────────────────────────────────────
def test_discovered_at_is_null_until_stamped(st):
    sid = _discovered_run(st)
    assert st.get_scan(sid, owner="dana@x.com")["run"]["completed_at"] is None


def test_mark_discovery_complete_records_the_instant(st):
    sid = _discovered_run(st)
    got = st.mark_discovery_complete(sid, "2026-08-19T10:05:00+00:00")
    assert got == "2026-08-19T10:05:00+00:00"
    assert st.get_discovery_completed_at(sid) == "2026-08-19T10:05:00+00:00"


def test_it_is_not_completed_at(st):
    """Discovery finishing and the SCAN finishing are different events, days apart or never."""
    sid = _discovered_run(st)
    st.mark_discovery_complete(sid, "2026-08-19T10:05:00+00:00")
    run = st.get_scan(sid, owner="dana@x.com")["run"]
    assert run["discovered_at"] == "2026-08-19T10:05:00+00:00"
    assert run["completed_at"] is None          # still awaiting an explicit Assess
    assert run["status"] == "discovered"


def test_stamp_defaults_to_now_when_no_instant_is_passed(st):
    sid = _discovered_run(st)
    assert st.mark_discovery_complete(sid)      # a UTC isoformat string, not None


def test_set_once_a_redelivered_discover_does_not_re_date_the_snapshot(st):
    """add_inventory preserves each row's original discovered_at through its ON CONFLICT; a
    run-level stamp that drifted while the per-file stamps did not would make the two disagree
    about one event."""
    sid = _discovered_run(st)
    st.mark_discovery_complete(sid, "2026-08-19T10:05:00+00:00")
    again = st.mark_discovery_complete(sid, "2026-08-20T23:00:00+00:00")
    assert again == "2026-08-19T10:05:00+00:00"
    assert st.get_discovery_completed_at(sid) == "2026-08-19T10:05:00+00:00"


def test_stamping_an_unknown_run_reports_nothing_rather_than_inventing_a_row(st):
    assert st.mark_discovery_complete("no-such-scan") is None


# ── runs discovered before the column existed ────────────────────────────────
def test_derives_from_the_newest_per_file_stamp_when_the_run_has_none(st):
    """Real persisted data, not a clock: add_inventory writes discovered_at per file at the
    moment the batch landed, so its maximum is when the inventory was last added to."""
    sid = _discovered_run(st)
    assert st.get_discovery_completed_at(sid) == "2026-08-19T10:04:00+00:00"


def test_get_scan_fills_the_derived_instant_so_the_header_need_not_page_the_inventory(st):
    sid = _discovered_run(st)
    assert st.get_scan(sid, owner="dana@x.com")["run"]["discovered_at"] == "2026-08-19T10:04:00+00:00"


def test_the_stamp_wins_over_the_derivation_once_it_exists(st):
    sid = _discovered_run(st)
    st.mark_discovery_complete(sid, "2026-08-19T10:05:00+00:00")
    assert st.get_discovery_completed_at(sid) == "2026-08-19T10:05:00+00:00"
    assert st.get_scan(sid, owner="dana@x.com")["run"]["discovered_at"] == "2026-08-19T10:05:00+00:00"


def test_no_inventory_and_no_stamp_reads_as_unknown_not_as_recent(st):
    st.init_scan_run("empty", "drive", 0, "2026-08-19T09:00:00+00:00", "acp", "h",
                     owner="dana@x.com", status="discovered")
    assert st.get_discovery_completed_at("empty") is None
    assert st.get_scan("empty", owner="dana@x.com")["run"]["discovered_at"] is None


# ── the discovery paths stamp it ─────────────────────────────────────────────
def test_persist_discovery_inventory_stamps_the_run(st, monkeypatch):
    """The shared post-discovery step every non-deferred path routes through."""
    import core
    import handlers
    monkeypatch.setattr(core, "store", st)
    monkeypatch.setattr(handlers, "_evaluate_discover_lifecycle_rules",
                        lambda *a, **k: {"rules_enabled": 0, "files_evaluated": 0, "lifecycle_matches": 0})
    st.init_scan_run("s2", "drive", 1, "2026-08-19T09:00:00+00:00", "acp", "h",
                     owner="dana@x.com")
    handlers.persist_discovery_inventory(
        "s2", [{"file": "a.docx", "doc_class": "document"}], "drive", "dana@x.com")
    assert st.get_scan("s2", owner="dana@x.com")["run"]["discovered_at"]


def test_a_failed_stamp_never_costs_the_inventory(st, monkeypatch):
    """The inventory is already written by the time the stamp runs. Losing the timestamp costs a
    date on a screen; raising would lose the listing the job just paid for."""
    import core
    import handlers

    class Boom:
        def __getattr__(self, name):
            if name == "mark_discovery_complete":
                def _raise(*a, **k):
                    raise RuntimeError("db went away")
                return _raise
            return getattr(st, name)

    monkeypatch.setattr(core, "store", Boom())
    monkeypatch.setattr(handlers, "_evaluate_discover_lifecycle_rules",
                        lambda *a, **k: {"rules_enabled": 0, "files_evaluated": 0, "lifecycle_matches": 0})
    st.init_scan_run("s3", "drive", 1, "2026-08-19T09:00:00+00:00", "acp", "h",
                     owner="dana@x.com")
    handlers.persist_discovery_inventory(
        "s3", [{"file": "a.docx", "doc_class": "document"}], "drive", "dana@x.com")
    assert st.count_inventory("s3") == 1        # the inventory survived the failed stamp


# ── the ADR 0020 Discover-only path is the reason this exists ────────────────
_PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"


def test_deferred_discover_dates_its_inventory(isolated_store, monkeypatch):
    """A Discover-only run stops at status='discovered' and may sit there forever. Without the
    stamp there is no record anywhere of when its inventory was taken, and the counts on the
    Discover screen are a snapshot with no date."""
    import core
    import handlers
    import scanner
    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setenv("ACP_DEFER_ANALYSIS_TO_ASSESS", "1")
    monkeypatch.setattr(scanner, "_list",
                        lambda *a, **k: [{"name": "deck.pptx", "id": "d1", "mime": _PPTX}])
    handlers._scan_discover({"scan_id": "sd", "source": "local", "user": None}, {"scan_id": "sd"})

    run = isolated_store.get_scan("sd")["run"]
    assert run["status"] == "discovered"
    assert run["completed_at"] is None          # nothing has been assessed
    assert run["discovered_at"]                 # …but the inventory IS dated
    assert isolated_store.get_discovery_completed_at("sd") == run["discovered_at"]


def test_an_estate_with_nothing_assessable_is_still_dated(isolated_store, monkeypatch):
    """The no-assessable-items branch returns early after enqueuing finalize. An inventory of
    100k media files is still an inventory, and still needs its instant."""
    import core
    import handlers
    import scanner
    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setenv("ACP_DEFER_ANALYSIS_TO_ASSESS", "1")
    monkeypatch.setattr(scanner, "_list", lambda *a, **k: [])
    handlers._scan_discover({"scan_id": "se", "source": "local", "user": None}, {"scan_id": "se"})
    assert isolated_store.get_scan("se")["run"]["discovered_at"]
