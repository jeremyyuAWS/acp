"""What a completed run's lifecycle rules HELD BACK, recorded onto the run itself.

THE GAP. Assess already excludes archive/delete-flagged files by default (PRD §4.5, Phase C3),
and `wcag_codeset.lifecycle_exclusion` already computes the pair for the pre-run scope preview.
But nothing was ever written onto the run, so once the run finished there was no record of it.
The Overview reconciliation panel reads `scope.lifecycle_eligible_excluded` and
`scope.lifecycle_overridden` and, finding nothing, renders "not recorded" for that bucket
permanently — correctly, since an absent count is not a measured zero.

WHAT IS RECORDED, and why each one is a distinct number:

  lifecycle_excluded           every flagged file, ANY format. The estate-wide fact.
  lifecycle_eligible_excluded  the ASSESSABLE subset actually held back — the only one that
                               belongs in the reconciliation, because it is disjoint from the
                               "no test exists" bucket by construction (it is counted only after
                               the assessable gate has already passed). A flagged .png was never
                               assessable and must not be counted twice.
  lifecycle_overridden         flagged files an authorized override assessed anyway. They ARE
                               assessed, so they belong to the assessed bucket and are reported
                               beside the lifecycle row, never as a sixth one.

THE LINE THESE CASES DEFEND. A count that was never measured must stay ABSENT — the panel
distinguishes "not recorded" from "measured zero", and collapsing the first into the second is a
reassuring answer to a question nobody asked. So: a run that reaches Assess and finds nothing
flagged writes 0 (it looked), and a run that never reaches Assess writes NOTHING AT ALL.

Harness mirrors test_discover_lifecycle_rules.py.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _items():
    """Two assessable .docx rows plus an IMAGE, all three under /Archive so one predicate flags
    every one of them.

    The image is the whole point of having a second number. It is flagged like the others, but it
    was never assessable — so it belongs in `lifecycle_excluded` and must NOT appear in
    `lifecycle_eligible_excluded`, or the reconciliation double-counts it against the "no test
    exists" bucket it already lives in.
    """
    return [
        {"name": "old.docx", "id": "d-old", "mime": _DOCX, "source_mime": _DOCX,
         "path": "/Archive/old.docx", "parent_folder": "/Archive", "owner": "cfo@x.com",
         "created_at": "2018-01-01T00:00:00+00:00", "source_modified": "2019-01-01T00:00:00+00:00",
         "size_kb": 10, "checksum": "c-old"},
        {"name": "older.docx", "id": "d-older", "mime": _DOCX, "source_mime": _DOCX,
         "path": "/Archive/older.docx", "parent_folder": "/Archive", "owner": "cfo@x.com",
         "created_at": "2017-01-01T00:00:00+00:00", "source_modified": "2018-01-01T00:00:00+00:00",
         "size_kb": 11, "checksum": "c-older"},
        {"name": "scan.png", "id": "d-png", "mime": "image/png", "source_mime": "image/png",
         "path": "/Archive/scan.png", "parent_folder": "/Archive", "owner": "cfo@x.com",
         "created_at": "2018-01-01T00:00:00+00:00", "source_modified": "2019-01-01T00:00:00+00:00",
         "size_kb": 90, "checksum": "c-png"},
        {"name": "new.docx", "id": "d-new", "mime": _DOCX, "source_mime": _DOCX,
         "path": "/Current/new.docx", "parent_folder": "/Current", "owner": "cfo@x.com",
         "created_at": "2025-01-01T00:00:00+00:00", "source_modified": "2025-06-01T00:00:00+00:00",
         "size_kb": 12, "checksum": "c-new"},
    ]


def _policy(st, name, action, match, *, enabled=True):
    pid = "p-" + name
    st.create_disposition_policy(pid, name=name, match=json.dumps(match), action=action,
                                 action_config="{}", requires_approval=False, enabled=enabled)
    return pid


def _wire(monkeypatch, st):
    import core
    import scanner
    monkeypatch.setattr(core, "store", st)
    monkeypatch.setenv("ACP_DEFER_ANALYSIS_TO_ASSESS", "1")
    monkeypatch.setattr(scanner, "_list", lambda *a, **k: _items())


def _discover(scan_id="s1", user="admin@x.com"):
    import handlers
    handlers._scan_discover({"scan_id": scan_id, "source": "local", "user": user},
                            {"scan_id": scan_id})


def _assess(scan_id="s1", **payload):
    import handlers
    handlers._scan_assess({"scan_id": scan_id, "user": "admin@x.com", **payload},
                          {"scan_id": scan_id})


def _scope(st, scan_id="s1"):
    return st.get_scan(scan_id)["run"]["scope"] or {}


ARCHIVE_FOLDER = [{"field": "path", "op": "prefix", "value": "/Archive/"}]


# ── The counts land on the run ───────────────────────────────────────────────────────────────

def test_a_completed_run_records_what_its_lifecycle_rules_held_back(isolated_store, monkeypatch):
    st = isolated_store
    _wire(monkeypatch, st)
    _policy(st, "archive-old", "archive", ARCHIVE_FOLDER)
    _discover()
    _assess()

    sc = _scope(st)
    # Three files under /Archive were flagged: two .docx and the .png.
    assert sc["lifecycle_excluded"] == 3
    # Only the two assessable ones were actually held back from Assess.
    assert sc["lifecycle_eligible_excluded"] == 2
    assert sc["lifecycle_overridden"] == 0


def test_the_eligible_count_excludes_a_flagged_file_that_was_never_assessable(isolated_store,
                                                                             monkeypatch):
    """The disjointness the reconciliation depends on. A flagged .png already sits in the "no test
    exists" bucket; counting it again under lifecycle makes the buckets sum past the discovered
    total and the panel reports an overlap that is not real."""
    st = isolated_store
    _wire(monkeypatch, st)
    _policy(st, "archive-old", "archive", ARCHIVE_FOLDER)
    _discover()
    _assess()

    sc = _scope(st)
    assert sc["lifecycle_excluded"] - sc["lifecycle_eligible_excluded"] == 1   # the .png
    # And the png was never enqueued for analysis either way.
    assert "scan.png" not in _enqueued(st)


def test_the_recorded_count_equals_the_files_actually_held_back(isolated_store, monkeypatch):
    """Counted where the holding-back happens, so it cannot disagree with what the run enqueued.
    Checked against the enqueued set rather than against itself."""
    st = isolated_store
    _wire(monkeypatch, st)
    _policy(st, "archive-old", "archive", ARCHIVE_FOLDER)
    _discover()
    _assess()

    assert _enqueued(st) == {"new.docx"}
    assessable = {"old.docx", "older.docx", "new.docx"}
    held_back = assessable - _enqueued(st)
    assert _scope(st)["lifecycle_eligible_excluded"] == len(held_back) == 2


def test_an_authorized_override_is_counted_separately_and_not_as_an_exclusion(isolated_store,
                                                                             monkeypatch):
    """Overridden files were assessed. They belong in the assessed bucket, reported beside the
    lifecycle row as "2 overridden and assessed" — never as files held back."""
    st = isolated_store
    _wire(monkeypatch, st)
    _policy(st, "archive-old", "archive", ARCHIVE_FOLDER)
    _discover()
    _assess(include_lifecycle_flagged=True)

    sc = _scope(st)
    assert sc["lifecycle_overridden"] == 2
    assert sc["lifecycle_eligible_excluded"] == 0      # nothing was held back
    assert sc["lifecycle_excluded"] == 3               # but three files are still flagged
    assert _enqueued(st) == {"old.docx", "older.docx", "new.docx"}


# ── Missing stays missing; measured zero stays zero ──────────────────────────────────────────

def test_a_run_that_never_reached_assess_records_nothing(isolated_store, monkeypatch):
    """The rule the frontend depends on. Discover alone has not decided anything about lifecycle
    exclusion, so it must not claim it measured zero — the panel must be able to say "not
    recorded" and mean it."""
    st = isolated_store
    _wire(monkeypatch, st)
    _policy(st, "archive-old", "archive", ARCHIVE_FOLDER)
    _discover()                                        # no _assess()

    sc = _scope(st)
    for key in ("lifecycle_excluded", "lifecycle_eligible_excluded", "lifecycle_overridden"):
        assert key not in sc, f"{key} must be ABSENT, not 0, on a run that never assessed"


def test_a_run_with_no_rules_records_a_measured_zero(isolated_store, monkeypatch):
    """The other side of the same rule. Assess ran, walked every inventory row and found nothing
    flagged — that IS zero, and reporting it as unknown would be just as wrong in the other
    direction."""
    st = isolated_store
    _wire(monkeypatch, st)
    _discover()                                        # no policies at all
    _assess()

    sc = _scope(st)
    assert sc["lifecycle_excluded"] == 0
    assert sc["lifecycle_eligible_excluded"] == 0
    assert sc["lifecycle_overridden"] == 0
    assert _enqueued(st) == {"old.docx", "older.docx", "new.docx"}


# ── The rest of the scope survives ───────────────────────────────────────────────────────────

def test_recording_the_counts_leaves_the_discovery_boundary_intact(isolated_store, monkeypatch):
    """`scope` is one JSON blob holding what discovery covered — the inventory, the kind, the
    kept count. Writing three keys onto it at Assess time must not cost any of that; a
    read-modify-write that dropped the inventory would blank the whole Overview, not just this
    panel."""
    st = isolated_store
    _wire(monkeypatch, st)
    _policy(st, "archive-old", "archive", ARCHIVE_FOLDER)
    _discover()
    before = _scope(st)
    assert before, "discovery must record a scope for this test to mean anything"
    _assess()
    after = _scope(st)

    for key, value in before.items():
        assert after[key] == value, f"scope['{key}'] was disturbed by the lifecycle write"


def test_the_merge_never_invents_a_scope_for_a_run_that_has_none(isolated_store):
    """merge_scan_scope on an unknown run is a no-op, not a new row and not a crash."""
    st = isolated_store
    st.merge_scan_scope("no-such-scan", {"lifecycle_excluded": 5})
    assert st.get_scan("no-such-scan") is None


def test_the_merge_leaves_an_unreadable_scope_alone(isolated_store):
    """An unreadable scope is already a loss. Overwriting it with a dict holding only these three
    keys would turn that into the loss of the discovery boundary as well."""
    st = isolated_store
    st.init_scan_run("s9", "local", 1, "2026-08-20T00:00:00+00:00", "r", "h")
    with st._db.cursor() as cur:
        st._db.execute(cur, "UPDATE scan_runs SET scope=%s WHERE id=%s", ("{not json", "s9"))
    st.merge_scan_scope("s9", {"lifecycle_excluded": 5})
    with st._db.cursor() as cur:
        st._db.execute(cur, "SELECT scope FROM scan_runs WHERE id=%s", ("s9",))
        assert st._db.fetchone(cur)["scope"] == "{not json"


def _enqueued(st):
    """Filenames Assess actually enqueued for analysis — the run's own answer to what it assessed,
    read from the job queue rather than from the counter under test."""
    out = set()
    for j in st.list_jobs():
        payload = j.get("payload")
        if isinstance(payload, str):
            payload = json.loads(payload or "{}")
        payload = payload or {}
        if j["type"] == "scan_file":
            out.add(payload.get("file"))
        elif j["type"] == "scan_batch":
            out |= {i.get("file") for i in payload.get("items") or []}
    return {f for f in out if f}
