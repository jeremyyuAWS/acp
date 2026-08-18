"""The discovery diff — what a source's estate gained, lost and changed between two runs.

WHY THIS IS NOT `get_scan_diff`. That method reads `file_records`, the ASSESSED grain. Under
ADR 0020 a Discover-only run persists `scan_inventory` and leaves `file_records` empty until
Assess runs, so pointing a discovery question at it answers "0 new · 0 changed · 0 removed" for
exactly the runs a source operations panel is about — confidently, and wrongly. The first test
below is that trap, pinned.

The other three pin the pairs that must not collapse into one another, each of which is a way of
reporting "we do not know" as "nothing happened":

  - `removed` vs `not_listed`, when the listing boundary moved or the listing hit its cap;
  - `changed` vs `indeterminate`, when neither a checksum nor a modified time is comparable —
    md5Checksum is absent for native Google Workspace files, so this is the common case, not
    the edge one;
  - a per-SOURCE baseline vs the immediately-prior scan, which with two connectors alternating
    is routinely the OTHER source: every file in it reads as removed and every file in this one
    as new.
"""
import sys, tempfile
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))


@pytest.fixture()
def st(monkeypatch):
    import store as store_mod
    monkeypatch.setattr(store_mod, "_SQLITE_PATH", Path(tempfile.mkdtemp()) / "invdiff.db")
    return store_mod.Store()


OWNER = "alex@example.com"


def run(st, sid, source="drive", scope=None, owner=OWNER, at="2026-08-18T10:00:00Z"):
    st.init_scan_run(sid, source, 0, at, "r", "h", owner=owner, status="discovered", scope=scope)
    return sid


def inv(st, sid, rows):
    st.add_inventory(sid, [{"file": f, "doc_class": "docx", **extra} for f, extra in rows.items()])


# ── the trap this module exists to avoid ─────────────────────────────────────

def test_reads_the_inventory_not_file_records(st):
    """A Discover-only run has an inventory and NO file_records. The diff must see it."""
    run(st, "prev"); run(st, "cur")
    inv(st, "prev", {"a.docx": {"checksum": "1"}})
    inv(st, "cur", {"a.docx": {"checksum": "1"}, "b.docx": {"checksum": "2"}})
    d = st.get_inventory_diff("cur", "prev", owner=OWNER)
    assert d["summary"]["new"] == 1
    assert [x["file"] for x in d["new"]] == ["b.docx"]
    # And for contrast: the assessed-grain diff sees nothing at all here.
    assert st.get_scan_diff("cur", "prev", owner=OWNER)["summary"]["new"] == 0


# ── new / removed / changed, same boundary ───────────────────────────────────

def test_new_removed_and_changed_by_checksum(st):
    run(st, "prev"); run(st, "cur")
    inv(st, "prev", {"keep.docx": {"checksum": "1"}, "edit.docx": {"checksum": "a"},
                     "gone.docx": {"checksum": "3"}})
    inv(st, "cur", {"keep.docx": {"checksum": "1"}, "edit.docx": {"checksum": "b"},
                    "fresh.docx": {"checksum": "4"}})
    s = st.get_inventory_diff("cur", "prev", owner=OWNER)["summary"]
    assert (s["new"], s["changed"], s["removed"], s["unchanged"]) == (1, 1, 1, 1)


def test_falls_back_to_modified_time_when_no_checksum(st):
    """Google-native files carry no md5Checksum; modifiedTime is what is left."""
    run(st, "prev"); run(st, "cur")
    inv(st, "prev", {"doc": {"source_modified": "2026-01-01T00:00:00Z"}})
    inv(st, "cur", {"doc": {"source_modified": "2026-02-01T00:00:00Z"}})
    d = st.get_inventory_diff("cur", "prev", owner=OWNER)
    assert d["summary"]["changed"] == 1
    assert d["changed"][0]["basis"] == "modified"


def test_unknowable_is_indeterminate_not_unchanged(st):
    """No checksum, no modified time. "We cannot tell" reported as "nothing happened" is the
    defect; the file is present in both runs and that is all we know."""
    run(st, "prev"); run(st, "cur")
    inv(st, "prev", {"native.gdoc": {}})
    inv(st, "cur", {"native.gdoc": {}})
    s = st.get_inventory_diff("cur", "prev", owner=OWNER)["summary"]
    assert s["indeterminate"] == 1
    assert s["unchanged"] == 0 and s["changed"] == 0


def test_a_checksum_on_one_side_only_does_not_claim_a_change(st):
    """Half a comparison is not a comparison — it falls through to modified time, then to
    indeterminate. Treating "had a checksum, now does not" as a change would flag every file
    the day a connector stopped returning them."""
    run(st, "prev"); run(st, "cur")
    inv(st, "prev", {"f.docx": {"checksum": "1"}})
    inv(st, "cur", {"f.docx": {}})
    s = st.get_inventory_diff("cur", "prev", owner=OWNER)["summary"]
    assert s["changed"] == 0 and s["indeterminate"] == 1


# ── removed vs not_listed ────────────────────────────────────────────────────

def test_a_narrower_boundary_does_not_delete_the_estate(st):
    """The get_scan_diff incident at the inventory grain: a folder-scoped run after a whole-drive
    one must not report everything outside the folder as removed."""
    run(st, "prev", scope={"kind": "drive"})
    run(st, "cur", scope={"kind": "folder", "folder": "Finance"})
    inv(st, "prev", {"Finance/a.docx": {"checksum": "1"}, "HR/b.docx": {"checksum": "2"}})
    inv(st, "cur", {"Finance/a.docx": {"checksum": "1"}})
    d = st.get_inventory_diff("cur", "prev", owner=OWNER)
    assert d["summary"]["removed"] == 0
    assert d["summary"]["not_listed"] == 1
    assert d["boundary_changed"] is True


def test_a_truncated_listing_cannot_claim_a_removal(st):
    """A capped listing did not see everything, so absence is not evidence of deletion."""
    run(st, "prev", scope={"kind": "drive"})
    run(st, "cur", scope={"kind": "drive", "truncated": True})
    inv(st, "prev", {"a.docx": {"checksum": "1"}, "b.docx": {"checksum": "2"}})
    inv(st, "cur", {"a.docx": {"checksum": "1"}})
    d = st.get_inventory_diff("cur", "prev", owner=OWNER)
    assert d["summary"]["removed"] == 0 and d["summary"]["not_listed"] == 1
    assert d["truncated"] is True


def test_same_boundary_does_report_a_removal(st):
    """The guard must not swallow the real case it exists to protect."""
    run(st, "prev", scope={"kind": "drive"})
    run(st, "cur", scope={"kind": "drive"})
    inv(st, "prev", {"a.docx": {"checksum": "1"}, "b.docx": {"checksum": "2"}})
    inv(st, "cur", {"a.docx": {"checksum": "1"}})
    d = st.get_inventory_diff("cur", "prev", owner=OWNER)
    assert d["summary"]["removed"] == 1 and d["summary"]["not_listed"] == 0
    assert d["boundary_changed"] is False


# ── owner scoping ────────────────────────────────────────────────────────────

def test_another_tenants_run_is_not_diffable(st):
    run(st, "prev", owner="someone@else.com"); run(st, "cur")
    inv(st, "prev", {"a.docx": {}})
    inv(st, "cur", {"a.docx": {}})
    assert st.get_inventory_diff("cur", "prev", owner=OWNER) is None


def test_missing_run_returns_none(st):
    run(st, "cur")
    assert st.get_inventory_diff("cur", "nope", owner=OWNER) is None


# ── the route, and the per-source baseline ───────────────────────────────────
#
# The baseline is the part of this feature most likely to be got wrong silently. `/scans/{id}/diff`
# defaults `vs` to the caller's immediately-prior scan across EVERY source — right for "did my
# estate regress", wrong for "what did OneDrive find this time". With two connectors alternating,
# the prior scan is routinely the other source, and the diff then reports every file in it as
# removed and every file in this one as new. Both numbers are large, both look like news, and
# nothing on screen says they are comparing Drive to OneDrive.

@pytest.fixture()
def client(monkeypatch, isolated_store):
    import core
    from fastapi.testclient import TestClient
    from app import app
    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setattr(core, "ACCESS_CODE", "", raising=False)
    monkeypatch.setattr(core, "GOOGLE_CLIENT_ID", "", raising=False)
    monkeypatch.setattr(core, "E2E_KEY", None, raising=False)
    monkeypatch.setattr(core, "OWNER_EMAIL", "", raising=False)
    return TestClient(app), isolated_store


def seed(store, sid, source, at, files, owner="demo", scope=None):
    """A Discover-only run: status='discovered', NO completed_at. That is the shape ADR 0020
    leaves behind until Assess runs, and the shape the baseline lookup has to cope with."""
    store.init_scan_run(sid, source, 0, at, "r", "h", owner=owner, status="discovered", scope=scope)
    store.add_inventory(sid, [{"file": f, "doc_class": "docx", "checksum": c} for f, c in files.items()])


def test_baseline_is_the_prior_run_of_THIS_source(client):
    c, st = client
    # Interleaved, newest last: drive → sharepoint → drive.
    seed(st, "d1", "drive", "2026-08-16T10:00:00Z", {"a.docx": "1", "b.docx": "2"},
         scope={"kind": "drive"})
    seed(st, "sp1", "sharepoint", "2026-08-17T10:00:00Z", {"z.docx": "9"},
         scope={"kind": "drive"})
    seed(st, "d2", "drive", "2026-08-18T10:00:00Z", {"a.docx": "1", "b.docx": "2", "c.docx": "3"},
         scope={"kind": "drive"})
    body = c.get("/scans/d2/inventory-diff").json()
    assert body["prev_id"] == "d1", "must skip the SharePoint run sitting between the two Drive runs"
    # One genuinely new file — not "3 new, 1 removed" from diffing against SharePoint.
    assert body["summary"]["new"] == 1
    assert body["summary"]["removed"] == 0


def test_no_baseline_is_stated_not_rendered_as_zeros(client):
    c, st = client
    seed(st, "d1", "drive", "2026-08-18T10:00:00Z", {"a.docx": "1"})
    body = c.get("/scans/d1/inventory-diff").json()
    assert body["no_baseline"] is True


def test_an_explicit_vs_is_honoured(client):
    c, st = client
    seed(st, "d1", "drive", "2026-08-16T10:00:00Z", {"a.docx": "1"}, scope={"kind": "drive"})
    seed(st, "d2", "drive", "2026-08-17T10:00:00Z", {"a.docx": "1", "b.docx": "2"},
         scope={"kind": "drive"})
    seed(st, "d3", "drive", "2026-08-18T10:00:00Z", {"a.docx": "1", "b.docx": "2", "c.docx": "3"},
         scope={"kind": "drive"})
    assert c.get("/scans/d3/inventory-diff?vs=d1").json()["summary"]["new"] == 2


def test_unknown_scan_is_a_404(client):
    c, _ = client
    assert c.get("/scans/nope/inventory-diff").status_code == 404


def test_an_unassessed_discover_run_still_counts_as_a_baseline(client):
    """The trap `previous_run_for_source` exists for: `list_scans` filters to completed scans, so
    a Discover-only run awaiting Assess is invisible to it. Basing the baseline on that filter
    reported "no baseline" for a source with a week of daily discoveries behind it."""
    c, st = client
    seed(st, "d1", "drive", "2026-08-17T10:00:00Z", {"a.docx": "1"}, scope={"kind": "drive"})
    seed(st, "d2", "drive", "2026-08-18T10:00:00Z", {"a.docx": "1", "b.docx": "2"},
         scope={"kind": "drive"})
    assert [s["id"] for s in st.list_scans(owner="demo")] == [], "precondition: neither run completed"
    body = c.get("/scans/d2/inventory-diff").json()
    assert body.get("no_baseline") is not True
    assert body["prev_id"] == "d1" and body["summary"]["new"] == 1
