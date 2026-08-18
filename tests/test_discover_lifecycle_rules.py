"""Lifecycle rules evaluated DURING Discover (candidate-first) + excluded from Assess.

Phase B4 (PRD §4.3 / §6): after Discover persists the inventory, enabled disposition policies
run against it and record CANDIDATE outcomes — an archive rule flags 'Archive Candidate', a
delete rule 'Delete Candidate', a tag rule writes system tags — WITHOUT executing any Drive
move/delete. Re-running Discover is idempotent. Archive-vs-delete precedence keeps the reversible
outcome unless a delete rule explicitly permits the override and the actor is authorized. An
Exempted file is never touched.

Phase C3 (PRD §4.5): Assess excludes archive/delete-flagged files by default, an authorized
override includes them, and either way the assess record retains the lifecycle status +
exclusion reason.

The harness mirrors test_deferred_assess.py: deferral ON, scanner._list monkeypatched to a fixed
listing, core.store pointed at an isolated temp Store.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _items():
    """Two assessable .docx rows: old.docx (in /Archive, modified 2019) and new.docx (in
    /Current, modified 2025). Every field Discover copies into the inventory row is present."""
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


def _policy(st, name, action, match, *, action_config=None, enabled=True):
    pid = "p-" + name
    st.create_disposition_policy(
        pid, name=name, match=json.dumps(match), action=action,
        action_config=json.dumps(action_config or {}), requires_approval=False, enabled=enabled)
    return pid


def _wire(monkeypatch, st, *, defer="1"):
    import core
    import scanner
    monkeypatch.setattr(core, "store", st)
    monkeypatch.setenv("ACP_DEFER_ANALYSIS_TO_ASSESS", defer)
    monkeypatch.setattr(scanner, "_list", lambda *a, **k: _items())


def _discover(scan_id="s1", user="admin@x.com"):
    import handlers
    handlers._scan_discover({"scan_id": scan_id, "source": "local", "user": user},
                            {"scan_id": scan_id})


# ── B4: archive rule flags a candidate with rule_id + reason ─────────────────────
def test_modified_before_archive_flags_candidate(isolated_store, monkeypatch):
    st = isolated_store
    _wire(monkeypatch, st)
    pid = _policy(st, "archive-stale", "archive",
                  [{"field": "modified_at", "op": "before", "value": "2020-01-01T00:00:00+00:00"}])
    _discover()

    old = st.get_lifecycle_status("s1", "old.docx")
    assert old["lifecycle_status"] == "Archive Candidate"
    assert old["lifecycle_rule_id"] == pid
    assert "archive-stale" in old["lifecycle_reason"]
    # the non-matching file stays Active — no candidate move
    assert st.get_lifecycle_status("s1", "new.docx")["lifecycle_status"] == "Active"
    # candidate-first: NO scan_file/scan_batch enqueued by Discover, and no Drive action taken
    jobs = st.list_jobs()
    assert not any(j["type"] in ("scan_file", "scan_batch") for j in jobs)


# ── B4: tag rule attaches system tags keyed by scan_id/file ─────────────────────
def test_tag_rule_tags_matching_files(isolated_store, monkeypatch):
    st = isolated_store
    _wire(monkeypatch, st)
    pid = _policy(st, "tag-archive-folder", "tag",
                  [{"field": "path", "op": "prefix", "value": "/Archive/"}],
                  action_config={"tags": ["Stale", "Review"]})
    _discover()

    tags = st.list_file_tags("s1", "old.docx")
    assert sorted(t["tag"] for t in tags) == ["Review", "Stale"]
    assert all(t["kind"] == "system" and t["rule_id"] == pid for t in tags)
    # a tag rule alone leaves lifecycle status Active (metadata-only, PRD §4.2)
    assert st.get_lifecycle_status("s1", "old.docx")["lifecycle_status"] == "Active"
    assert st.list_file_tags("s1", "new.docx") == []


# ── B4: re-running Discover is idempotent (AC-13) ────────────────────────────────
def test_rediscover_is_idempotent(isolated_store, monkeypatch):
    st = isolated_store
    _wire(monkeypatch, st)
    _policy(st, "archive-stale", "archive",
            [{"field": "modified_at", "op": "before", "value": "2020-01-01T00:00:00+00:00"}])
    _policy(st, "tag-archive-folder", "tag",
            [{"field": "path", "op": "prefix", "value": "/Archive/"}],
            action_config={"tags": ["Stale"]})
    _discover()
    _discover()  # unchanged inputs + rules → no new actions

    assert [t["tag"] for t in st.list_file_tags("s1", "old.docx")] == ["Stale"]  # no dup tag
    audit = st.list_disposition_audit()
    # exactly two audit rows for old.docx: one tag (applied) + one archive candidate (pending).
    old_rows = [a for a in audit if a["doc_id"] == "scan:s1:old.docx"]
    assert len(old_rows) == 2
    assert {a["action"] for a in old_rows} == {"tag", "archive"}


# ── B4: archive-vs-delete precedence (PRD §6) ────────────────────────────────────
def test_delete_supersedes_archive_only_when_permitted_and_authorized(isolated_store, monkeypatch):
    st = isolated_store
    _wire(monkeypatch, st)
    _policy(st, "a-archive", "archive",
            [{"field": "path", "op": "prefix", "value": "/Archive/"}])
    _policy(st, "b-delete", "delete",
            [{"field": "path", "op": "prefix", "value": "/Archive/"}],
            action_config={"override_archive": True})
    _discover(user="admin@x.com")  # permitted override + authorized actor → Delete wins
    got = st.get_lifecycle_status("s1", "old.docx")
    assert got["lifecycle_status"] == "Delete Candidate"
    assert got["lifecycle_rule_id"] == "p-b-delete"


def test_delete_does_not_supersede_without_override_flag(isolated_store, monkeypatch):
    st = isolated_store
    _wire(monkeypatch, st)
    _policy(st, "a-archive", "archive",
            [{"field": "path", "op": "prefix", "value": "/Archive/"}])
    _policy(st, "b-delete", "delete",  # no override_archive flag
            [{"field": "path", "op": "prefix", "value": "/Archive/"}])
    _discover(user="admin@x.com")
    got = st.get_lifecycle_status("s1", "old.docx")
    assert got["lifecycle_status"] == "Archive Candidate"       # safe default kept
    assert got["lifecycle_rule_id"] == "p-a-archive"
    assert "flagged for review" in got["lifecycle_reason"]


def test_delete_does_not_supersede_for_unauthorized_actor(isolated_store, monkeypatch):
    st = isolated_store
    _wire(monkeypatch, st)
    _policy(st, "a-archive", "archive",
            [{"field": "path", "op": "prefix", "value": "/Archive/"}])
    _policy(st, "b-delete", "delete",
            [{"field": "path", "op": "prefix", "value": "/Archive/"}],
            action_config={"override_archive": True})
    _discover(user="demo")  # keyless/demo actor is not authorized for the irreversible-leaning move
    assert st.get_lifecycle_status("s1", "old.docx")["lifecycle_status"] == "Archive Candidate"


# ── B4: an Exempted file is never touched ────────────────────────────────────────
def test_exempted_file_is_never_moved_or_tagged(isolated_store, monkeypatch):
    st = isolated_store
    _wire(monkeypatch, st)
    # Seed + Exempt old.docx BEFORE Discover; re-listing preserves the status (store idempotency),
    # and rule evaluation must skip it entirely.
    st.add_inventory("s1", [{"file": "old.docx", "doc_class": "text-document"}])
    st.set_lifecycle_status("s1", "old.docx", "Exempted", reason="legal hold")
    _policy(st, "archive-stale", "archive",
            [{"field": "modified_at", "op": "before", "value": "2020-01-01T00:00:00+00:00"}])
    _policy(st, "tag-archive-folder", "tag",
            [{"field": "path", "op": "prefix", "value": "/Archive/"}],
            action_config={"tags": ["Stale"]})
    _discover()

    got = st.get_lifecycle_status("s1", "old.docx")
    assert got["lifecycle_status"] == "Exempted"          # untouched
    assert got["lifecycle_reason"] == "legal hold"        # reason not overwritten
    assert st.list_file_tags("s1", "old.docx") == []      # no tags applied
    assert st.list_disposition_audit() == []              # nothing audited for it


# ── C3: Assess excludes flagged files by default; authorized override includes them ─
def _enqueued_files(st):
    return {json.loads(j["payload"])["file"] for j in st.list_jobs()
            if j["type"] == "scan_file"}


def test_assess_excludes_flagged_by_default_and_records_reason(isolated_store, monkeypatch):
    st = isolated_store
    _wire(monkeypatch, st)
    _policy(st, "archive-stale", "archive",
            [{"field": "modified_at", "op": "before", "value": "2020-01-01T00:00:00+00:00"}])
    _discover()                                    # flags old.docx Archive Candidate
    import handlers
    handlers._scan_assess({"scan_id": "s1", "user": "admin@x.com"}, {"scan_id": "s1"})

    # old.docx (Archive Candidate) is excluded; new.docx (Active) is assessed
    assert _enqueued_files(st) == {"new.docx"}
    # the assess record retains the lifecycle status AND the exclusion reason that applied
    got = st.get_lifecycle_status("s1", "old.docx")
    assert got["lifecycle_status"] == "Archive Candidate"
    assert got["lifecycle_rule_id"] == "p-archive-stale"
    assert got["exclusion_reason"] and "excluded from Assess" in got["exclusion_reason"]
    assert "Archive Candidate" in got["exclusion_reason"]


def test_assess_override_includes_flagged_and_records_it(isolated_store, monkeypatch):
    st = isolated_store
    _wire(monkeypatch, st)
    _policy(st, "archive-stale", "archive",
            [{"field": "modified_at", "op": "before", "value": "2020-01-01T00:00:00+00:00"}])
    _discover()
    import handlers
    handlers._scan_assess(
        {"scan_id": "s1", "user": "admin@x.com", "include_lifecycle_flagged": True},
        {"scan_id": "s1"})

    # both files assessed under the authorized override
    assert _enqueued_files(st) == {"old.docx", "new.docx"}
    got = st.get_lifecycle_status("s1", "old.docx")
    assert got["lifecycle_status"] == "Archive Candidate"          # status preserved
    assert got["exclusion_reason"] and "authorized override" in got["exclusion_reason"]
