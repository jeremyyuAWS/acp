"""Six lifecycle-rule gaps not covered by test_discover_lifecycle_rules.py.

Each test wires the same minimal harness (deferral ON, scanner._list monkeypatched,
store isolated) and exercises one previously-untested behaviour of the Discover
lifecycle evaluator.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _items_with_null_dates():
    """One file with all date fields absent (None-equivalent strings) — used to test that
    age_days / modified_age_days rules never fire when the date is unknown."""
    return [
        {"name": "nodates.docx", "id": "d-nodates", "mime": _DOCX, "source_mime": _DOCX,
         "path": "/Finance/nodates.docx", "parent_folder": "/Finance", "owner": "cfo@x.com",
         "created_at": None, "source_modified": None, "size_kb": 5, "checksum": "c-nd"},
    ]


def _items():
    return [
        {"name": "old.docx", "id": "d-old", "mime": _DOCX, "source_mime": _DOCX,
         "path": "/Archive/old.docx", "parent_folder": "/Archive", "owner": "cfo@x.com",
         "created_at": "2018-01-01T00:00:00+00:00", "source_modified": "2019-01-01T00:00:00+00:00",
         "size_kb": 10, "checksum": "c-old"},
        {"name": "new.docx", "id": "d-new", "mime": _DOCX, "source_mime": _DOCX,
         "path": "/Current/new.docx", "parent_folder": "/Current", "owner": "cfo@x.com",
         "created_at": "2025-01-01T00:00:00+00:00", "source_modified": "2025-06-01T00:00:00+00:00",
         "size_kb": 12, "checksum": "c-new"},
    ]


def _policy(st, name, action, match, *, action_config=None, enabled=True, owner="admin@x.com"):
    pid = "p-" + name
    st.create_disposition_policy(
        pid, name=name, match=json.dumps(match), action=action,
        action_config=json.dumps(action_config or {}), requires_approval=False, enabled=enabled,
        owner_email=owner)
    return pid


def _wire(monkeypatch, st, items_fn=None):
    import core
    import scanner
    monkeypatch.setattr(core, "store", st)
    monkeypatch.setenv("ACP_DEFER_ANALYSIS_TO_ASSESS", "1")
    monkeypatch.setattr(scanner, "_list", lambda *a, **k: (items_fn or _items)())


def _discover(scan_id="s1", user="admin@x.com"):
    import handlers
    handlers._scan_discover({"scan_id": scan_id, "source": "local", "user": user},
                            {"scan_id": scan_id})


def _enqueued_files(st):
    return {json.loads(j["payload"])["file"] for j in st.list_jobs() if j["type"] == "scan_file"}


# ── Gap 1: `contains` operator fires end-to-end through Discover ─────────────────
def test_contains_operator_flags_matching_files(isolated_store, monkeypatch):
    st = isolated_store
    _wire(monkeypatch, st)
    pid = _policy(st, "archive-folder", "archive",
                  [{"field": "path", "op": "contains", "value": "Archive"}])
    _discover()

    old = st.get_lifecycle_status("s1", "old.docx")
    assert old["lifecycle_status"] == "Archive Candidate"
    assert old["lifecycle_rule_id"] == pid
    # new.docx path contains "Current", not "Archive" — must stay Active
    assert st.get_lifecycle_status("s1", "new.docx")["lifecycle_status"] == "Active"


def test_contains_operator_is_case_insensitive(isolated_store, monkeypatch):
    st = isolated_store
    _wire(monkeypatch, st)
    _policy(st, "archive-folder", "archive",
            [{"field": "path", "op": "contains", "value": "archive"}])  # lowercase
    _discover()

    # disposition._OPS["contains"] lowercases both sides
    assert st.get_lifecycle_status("s1", "old.docx")["lifecycle_status"] == "Archive Candidate"


# ── Gap 2: None / missing dates never satisfy age_days or modified_age_days rules ──
def test_null_created_at_does_not_match_age_days_rule(isolated_store, monkeypatch):
    """A file with created_at=None must never match an age_days rule — None yields
    None from _days_since, and the gt/gte/lt/lte operators all return False for None."""
    st = isolated_store
    _wire(monkeypatch, st, items_fn=_items_with_null_dates)
    _policy(st, "old-docs", "archive",
            [{"field": "age_days", "op": "gt", "value": 0}])
    _discover()

    assert st.get_lifecycle_status("s1", "nodates.docx")["lifecycle_status"] == "Unevaluable"
    assert st.list_disposition_audit() == []


def test_null_source_modified_does_not_match_modified_age_days_rule(isolated_store, monkeypatch):
    st = isolated_store
    _wire(monkeypatch, st, items_fn=_items_with_null_dates)
    _policy(st, "stale-modified", "archive",
            [{"field": "modified_age_days", "op": "gt", "value": 0}])
    _discover()

    assert st.get_lifecycle_status("s1", "nodates.docx")["lifecycle_status"] == "Unevaluable"
    assert st.list_disposition_audit() == []


# ── Gap 3: a disabled policy is silently skipped ─────────────────────────────────
def test_disabled_policy_produces_no_candidates_and_no_audit(isolated_store, monkeypatch):
    st = isolated_store
    _wire(monkeypatch, st)
    _policy(st, "archive-all", "archive",
            [{"field": "path", "op": "prefix", "value": "/"}],
            enabled=False)   # <-- disabled
    _discover()

    # Every file stays Active — the disabled rule is a no-op
    assert st.get_lifecycle_status("s1", "old.docx")["lifecycle_status"] == "Active"
    assert st.get_lifecycle_status("s1", "new.docx")["lifecycle_status"] == "Active"
    assert st.list_disposition_audit() == []


# ── Gap 4: actor-scoped isolation — another owner's policy is not applied ─────────
def test_other_actors_policy_is_not_evaluated(isolated_store, monkeypatch):
    """Policies owned by alice@x.com must NOT fire when bob@x.com runs Discover.
    The evaluator in handlers._evaluate_discover_lifecycle_rules filters policies by
    the discovering scan's owner_email."""
    st = isolated_store
    _wire(monkeypatch, st)
    _policy(st, "alice-archive", "archive",
            [{"field": "path", "op": "prefix", "value": "/Archive/"}],
            owner="alice@x.com")  # owned by alice, not by bob
    _discover(user="bob@x.com")   # bob runs Discover

    # bob's run must not have applied alice's rule
    assert st.get_lifecycle_status("s1", "old.docx")["lifecycle_status"] == "Active"
    assert st.list_disposition_audit() == []


def test_own_policy_is_evaluated(isolated_store, monkeypatch):
    """Sanity: a policy owned by the discovering actor IS applied."""
    st = isolated_store
    _wire(monkeypatch, st)
    _policy(st, "alice-archive", "archive",
            [{"field": "path", "op": "prefix", "value": "/Archive/"}],
            owner="alice@x.com")
    _discover(user="alice@x.com")  # alice runs Discover — her own rule fires

    assert st.get_lifecycle_status("s1", "old.docx")["lifecycle_status"] == "Archive Candidate"


# ── Gap 5: two tag rules on the same file write no duplicate tags ─────────────────
def test_two_tag_rules_on_same_file_produce_no_duplicate_tags(isolated_store, monkeypatch):
    """Both rules match old.docx and each adds a different tag — result is both tags, no
    duplicates. The existing idempotency test covers RE-RUNNING the same rule; this covers
    TWO DIFFERENT rules in a single run both tagging the same file."""
    st = isolated_store
    _wire(monkeypatch, st)
    pid1 = _policy(st, "tag-stale", "tag",
                   [{"field": "path", "op": "prefix", "value": "/Archive/"}],
                   action_config={"tags": ["Stale"]})
    pid2 = _policy(st, "tag-cfo", "tag",
                   [{"field": "owner", "op": "eq", "value": "cfo@x.com"}],
                   action_config={"tags": ["CFO-owned"]})
    _discover()

    tags = st.list_file_tags("s1", "old.docx")
    tag_names = sorted(t["tag"] for t in tags)
    assert tag_names == ["CFO-owned", "Stale"]   # both applied, no duplicates
    rule_ids = {t["rule_id"] for t in tags}
    assert rule_ids == {pid1, pid2}

    # new.docx matches only the cfo-owner rule (not in /Archive/)
    new_tags = [t["tag"] for t in st.list_file_tags("s1", "new.docx")]
    assert new_tags == ["CFO-owned"]


def test_overlapping_tag_rules_do_not_duplicate_same_tag(isolated_store, monkeypatch):
    """Two rules that both add the SAME tag to the same file must not double-write it."""
    st = isolated_store
    _wire(monkeypatch, st)
    _policy(st, "tag-a", "tag",
            [{"field": "path", "op": "prefix", "value": "/Archive/"}],
            action_config={"tags": ["Review"]})
    _policy(st, "tag-b", "tag",
            [{"field": "owner", "op": "eq", "value": "cfo@x.com"}],
            action_config={"tags": ["Review"]})   # same tag, different rule
    _discover()

    tags = st.list_file_tags("s1", "old.docx")
    assert [t["tag"] for t in tags].count("Review") == 1   # exactly one, not two


# ── Gap 6: Delete Candidate is also excluded from Assess by default ───────────────
def test_delete_candidate_excluded_from_assess_by_default(isolated_store, monkeypatch):
    st = isolated_store
    _wire(monkeypatch, st)
    _policy(st, "delete-stale", "delete",
            [{"field": "modified_at", "op": "before", "value": "2020-01-01T00:00:00+00:00"}],
            action_config={"override_archive": False})
    _discover()

    assert st.get_lifecycle_status("s1", "old.docx")["lifecycle_status"] == "Delete Candidate"

    import handlers
    handlers._scan_assess({"scan_id": "s1", "user": "admin@x.com"}, {"scan_id": "s1"})

    # old.docx (Delete Candidate) excluded; only new.docx assessed
    assert _enqueued_files(st) == {"new.docx"}
    got = st.get_lifecycle_status("s1", "old.docx")
    assert got["exclusion_reason"] and "excluded from Assess" in got["exclusion_reason"]
    assert "Delete Candidate" in got["exclusion_reason"]


def test_delete_candidate_included_under_authorized_override(isolated_store, monkeypatch):
    st = isolated_store
    _wire(monkeypatch, st)
    _policy(st, "delete-stale", "delete",
            [{"field": "modified_at", "op": "before", "value": "2020-01-01T00:00:00+00:00"}],
            action_config={"override_archive": False})
    _discover()

    import handlers
    handlers._scan_assess(
        {"scan_id": "s1", "user": "admin@x.com", "include_lifecycle_flagged": True},
        {"scan_id": "s1"})

    assert _enqueued_files(st) == {"old.docx", "new.docx"}
    got = st.get_lifecycle_status("s1", "old.docx")
    assert got["exclusion_reason"] and "authorized override" in got["exclusion_reason"]
