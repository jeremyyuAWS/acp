"""Discover-completeness foundation (lifecycle PRD): enriched inventory metadata,
per-file tags, and per-document lifecycle status. Schema + accessors only."""
import sys, tempfile
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))


@pytest.fixture()
def st(monkeypatch):
    import store as store_mod
    monkeypatch.setattr(store_mod, "_SQLITE_PATH", Path(tempfile.mkdtemp()) / "invlc.db")
    return store_mod.Store()


# ── enriched inventory metadata ──────────────────────────────────────────────
def test_inventory_persists_full_metadata(st):
    st.add_inventory("s1", [{
        "file": "Finance/budget.xlsx", "drive_file_id": "drv1", "mime": "application/vnd.ms-excel",
        "size_kb": 42, "doc_class": "xlsx", "checksum": "abc", "path": "Finance/budget.xlsx",
        "created_at": "2023-01-01T00:00:00+00:00", "source_modified": "2024-06-01T00:00:00+00:00",
        "owner": "cfo@x.com", "parent_folder": "Finance", "discovered_at": "2026-08-18T00:00:00+00:00",
    }])
    rows = st.list_inventory("s1")
    assert len(rows) == 1
    r = rows[0]
    assert r["created_at"] == "2023-01-01T00:00:00+00:00"
    assert r["source_modified"] == "2024-06-01T00:00:00+00:00"
    assert r["owner"] == "cfo@x.com"
    assert r["parent_folder"] == "Finance"
    assert r["discovered_at"] == "2026-08-18T00:00:00+00:00"
    # every discovered file starts Active
    assert r["lifecycle_status"] == "Active"


def test_discovered_at_defaults_when_absent(st):
    st.add_inventory("s1", [{"file": "a.bin", "doc_class": "unsupported"}])
    assert st.list_inventory("s1")[0]["discovered_at"]  # stamped by the store


def test_all_types_inventoried(st):
    # the PRD's core promise: unsupported/media/extensionless rows persist like any other
    st.add_inventory("s1", [
        {"file": "movie.mp4", "doc_class": "media"},
        {"file": "archive.zip", "doc_class": "unsupported"},
        {"file": "README", "doc_class": "unknown"},
    ])
    assert st.count_inventory("s1") == 3


# ── lifecycle status ─────────────────────────────────────────────────────────
def test_lifecycle_transition_records_rule_and_reason(st):
    st.add_inventory("s1", [{"file": "old.pdf", "doc_class": "pdf"}])
    st.set_lifecycle_status("s1", "old.pdf", "Archive Candidate",
                            rule_id="r-42", reason="modified before 2020-01-01")
    got = st.get_lifecycle_status("s1", "old.pdf")
    assert got["lifecycle_status"] == "Archive Candidate"
    assert got["lifecycle_rule_id"] == "r-42"
    assert got["lifecycle_reason"] == "modified before 2020-01-01"


def test_unknown_lifecycle_status_rejected(st):
    st.add_inventory("s1", [{"file": "x.pdf", "doc_class": "pdf"}])
    with pytest.raises(ValueError):
        st.set_lifecycle_status("s1", "x.pdf", "Nonsense")


def test_relist_does_not_reset_lifecycle_status(st):
    # PRD §4.3 idempotency: a re-run Discover must not clobber an assigned status
    st.add_inventory("s1", [{"file": "d.docx", "doc_class": "docx", "size_kb": 1}])
    st.set_lifecycle_status("s1", "d.docx", "Delete Candidate", reason="in /tmp")
    st.add_inventory("s1", [{"file": "d.docx", "doc_class": "docx", "size_kb": 2}])  # re-list, new size
    row = st.list_inventory("s1")[0]
    assert row["size_kb"] == 2                       # metadata refreshed
    assert row["lifecycle_status"] == "Delete Candidate"   # status preserved


def test_count_lifecycle_by_status(st):
    st.add_inventory("s1", [{"file": f"f{i}.pdf", "doc_class": "pdf"} for i in range(4)])
    st.set_lifecycle_status("s1", "f0.pdf", "Archived", reason="x")
    st.set_lifecycle_status("s1", "f1.pdf", "Exempted", reason="legal hold")
    counts = st.count_lifecycle_by_status("s1")
    assert counts["Active"] == 2 and counts["Archived"] == 1 and counts["Exempted"] == 1


# ── per-file tags ────────────────────────────────────────────────────────────
def test_tags_add_list_idempotent(st):
    st.add_inventory("s1", [{"file": "hr/policy.docx", "doc_class": "docx"}])
    st.add_file_tags("s1", "hr/policy.docx", ["HR", "Confidential"], kind="system", rule_id="r-1")
    st.add_file_tags("s1", "hr/policy.docx", ["HR"], kind="system", rule_id="r-1")  # dup
    tags = st.list_file_tags("s1", "hr/policy.docx")
    assert sorted(t["tag"] for t in tags) == ["Confidential", "HR"]  # no duplicate HR
    assert all(t["kind"] == "system" and t["rule_id"] == "r-1" for t in tags)


def test_tags_for_scan_and_remove(st):
    st.add_inventory("s1", [{"file": "a.pdf"}, {"file": "b.pdf"}])
    st.add_file_tags("s1", "a.pdf", ["x", "y"])
    st.add_file_tags("s1", "b.pdf", ["z"])
    by_file = st.list_tags_for_scan("s1")
    assert by_file == {"a.pdf": ["x", "y"], "b.pdf": ["z"]}
    st.remove_file_tag("s1", "a.pdf", "x")
    assert st.list_tags_for_scan("s1")["a.pdf"] == ["y"]
