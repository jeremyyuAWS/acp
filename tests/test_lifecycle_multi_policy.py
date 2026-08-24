"""Multi-policy lifecycle rule scenarios: tie-breaking, key aliases, tag+archive combos.

Two layers:

1. Pure unit tests on disposition.resolve_candidate() — no DB, no monkeypatching.
   resolve_candidate is pure and exported, so these run in microseconds and give
   exact coverage of every branch:
     - only-delete / only-archive / only-tag → correct status or None
     - supersedes_archive / supersede_archive key aliases (not just override_archive)
     - first-archive-wins when two archives match (priority order is the caller's job;
       resolve_candidate takes the list already sorted)
     - first-delete-wins when two deletes match
     - delete-supersedes-both-archives when three policies match

2. Handler-level tests (isolated_store + monkeypatch) for scenarios that need the
   full _evaluate_discover_lifecycle_rules() loop:
     - supersedes_archive alias wired end-to-end through the handler
     - tag + archive combo: status is Archive Candidate AND tags are attached
"""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

from disposition import resolve_candidate


# ── helpers ──────────────────────────────────────────────────────────────────

def _p(policy_id, action, action_config=None, *, name=None):
    """Minimal policy dict for resolve_candidate()."""
    return {
        "policy_id": policy_id,
        "name": name or policy_id,
        "action": action,
        "action_config": json.dumps(action_config or {}),
    }


_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _days_ago(n: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=n)).isoformat()


# ── resolve_candidate: single-action cases ────────────────────────────────────

def test_only_delete_yields_delete_candidate():
    chosen, status, reason = resolve_candidate([_p("d1", "delete")], "admin@x.com")
    assert status == "Delete Candidate"
    assert chosen["policy_id"] == "d1"
    assert reason


def test_only_archive_yields_archive_candidate():
    chosen, status, reason = resolve_candidate([_p("a1", "archive")], "admin@x.com")
    assert status == "Archive Candidate"
    assert chosen["policy_id"] == "a1"


def test_only_tag_yields_no_status():
    chosen, status, reason = resolve_candidate([_p("t1", "tag")], "admin@x.com")
    assert chosen is None
    assert status is None
    assert reason is None


def test_empty_matched_list_yields_no_status():
    chosen, status, reason = resolve_candidate([], "admin@x.com")
    assert chosen is None and status is None and reason is None


# ── resolve_candidate: key aliases for delete-supersedes-archive ──────────────

def test_override_archive_key_permits_delete_to_win():
    a = _p("a1", "archive")
    d = _p("d1", "delete", {"override_archive": True})
    _, status, _ = resolve_candidate([a, d], "admin@x.com")
    assert status == "Delete Candidate"


def test_supersedes_archive_key_alias_permits_delete_to_win():
    a = _p("a1", "archive")
    d = _p("d1", "delete", {"supersedes_archive": True})
    _, status, _ = resolve_candidate([a, d], "admin@x.com")
    assert status == "Delete Candidate"


def test_supersede_archive_key_alias_permits_delete_to_win():
    a = _p("a1", "archive")
    d = _p("d1", "delete", {"supersede_archive": True})
    _, status, _ = resolve_candidate([a, d], "admin@x.com")
    assert status == "Delete Candidate"


def test_none_of_the_alias_keys_means_archive_wins():
    a = _p("a1", "archive")
    d = _p("d1", "delete", {"some_other_key": True})
    _, status, _ = resolve_candidate([a, d], "admin@x.com")
    assert status == "Archive Candidate"


# ── resolve_candidate: tie-breaking within the same action ───────────────────

def test_first_archive_wins_when_two_archives_match():
    """Caller supplies policies in priority order; resolve_candidate picks the first."""
    a1 = _p("a1", "archive", name="first-archive")
    a2 = _p("a2", "archive", name="second-archive")
    chosen, status, _ = resolve_candidate([a1, a2], "admin@x.com")
    assert status == "Archive Candidate"
    assert chosen["policy_id"] == "a1"


def test_first_delete_wins_when_two_deletes_match():
    d1 = _p("d1", "delete", name="first-delete")
    d2 = _p("d2", "delete", name="second-delete")
    chosen, status, _ = resolve_candidate([d1, d2], "admin@x.com")
    assert status == "Delete Candidate"
    assert chosen["policy_id"] == "d1"


def test_delete_supersedes_multiple_archives():
    """When multiple archives and one authorized delete all match, delete wins over all."""
    a1 = _p("a1", "archive")
    a2 = _p("a2", "archive")
    d = _p("d1", "delete", {"override_archive": True})
    _, status, _ = resolve_candidate([a1, a2, d], "admin@x.com")
    assert status == "Delete Candidate"


def test_delete_supersede_blocked_for_demo_actor_even_with_flag():
    a = _p("a1", "archive")
    d = _p("d1", "delete", {"override_archive": True})
    _, status, _ = resolve_candidate([a, d], "demo")
    assert status == "Archive Candidate"


# ── handler-level: supersedes_archive alias wired end-to-end ─────────────────

def _policy(st, name, action, match, *, action_config=None, owner="admin@x.com"):
    pid = "p-" + name
    st.create_disposition_policy(
        pid, name=name, match=json.dumps(match), action=action,
        action_config=json.dumps(action_config or {}), requires_approval=False,
        enabled=True, owner_email=owner)
    return pid


def _wire(monkeypatch, st, items_fn):
    import core
    import scanner
    monkeypatch.setattr(core, "store", st)
    monkeypatch.setenv("ACP_DEFER_ANALYSIS_TO_ASSESS", "1")
    monkeypatch.setattr(scanner, "_list", lambda *a, **k: items_fn())


def _discover(scan_id="s1", user="admin@x.com"):
    import handlers
    handlers._scan_discover({"scan_id": scan_id, "source": "local", "user": user},
                            {"scan_id": scan_id})


def _one_old_docx():
    return [{"name": "old.docx", "id": "d-old", "mime": _DOCX, "source_mime": _DOCX,
             "path": "/Archive/old.docx", "parent_folder": "/Archive", "owner": "cfo@x.com",
             "created_at": "2018-01-01T00:00:00+00:00",
             "source_modified": "2019-01-01T00:00:00+00:00",
             "size_kb": 10, "checksum": "c-old", "doc_class": "text-document", "source": "drive"}]


def test_supersedes_archive_alias_via_handler(isolated_store, monkeypatch):
    """supersedes_archive (not override_archive) lets a delete rule beat an archive rule
    through the full _evaluate_discover_lifecycle_rules() loop."""
    st = isolated_store
    _wire(monkeypatch, st, _one_old_docx)
    _policy(st, "a-archive", "archive",
            [{"field": "path", "op": "prefix", "value": "/Archive/"}])
    _policy(st, "b-delete", "delete",
            [{"field": "path", "op": "prefix", "value": "/Archive/"}],
            action_config={"supersedes_archive": True})
    _discover()
    got = st.get_lifecycle_status("s1", "old.docx")
    assert got["lifecycle_status"] == "Delete Candidate"
    assert got["lifecycle_rule_id"] == "p-b-delete"


# ── handler-level: tag + archive combo ───────────────────────────────────────

def test_tag_and_archive_both_applied_to_same_file(isolated_store, monkeypatch):
    """When both a tag rule and an archive rule match, the file gets Archive Candidate
    status AND system tags — both paths run independently inside the evaluator."""
    st = isolated_store
    _wire(monkeypatch, st, _one_old_docx)
    _policy(st, "tag-archive-folder", "tag",
            [{"field": "path", "op": "prefix", "value": "/Archive/"}],
            action_config={"tags": ["Stale", "Review"]})
    _policy(st, "archive-stale", "archive",
            [{"field": "modified_at", "op": "before", "value": "2020-01-01T00:00:00+00:00"}])
    _discover()

    got = st.get_lifecycle_status("s1", "old.docx")
    assert got["lifecycle_status"] == "Archive Candidate", \
        "archive rule must set status even when a tag rule also matched"

    tags = sorted(t["tag"] for t in st.list_file_tags("s1", "old.docx"))
    assert tags == ["Review", "Stale"], \
        "tag rule must attach tags even though archive rule also matched"


def test_tag_only_leaves_status_active_when_no_archive_or_delete_rule(isolated_store, monkeypatch):
    """A tag rule alone must NOT change lifecycle_status from Active (metadata-only action)."""
    st = isolated_store
    _wire(monkeypatch, st, _one_old_docx)
    _policy(st, "tag-archive-folder", "tag",
            [{"field": "path", "op": "prefix", "value": "/Archive/"}],
            action_config={"tags": ["Flagged"]})
    _discover()

    got = st.get_lifecycle_status("s1", "old.docx")
    assert got["lifecycle_status"] == "Active"
    assert [t["tag"] for t in st.list_file_tags("s1", "old.docx")] == ["Flagged"]
