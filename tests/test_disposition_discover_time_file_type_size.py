"""doc_class ("file type") and size_kb ("larger than") rules must actually tag files at Discover
time, not just validate and preview.

THE DEFECT: #610 added `doc_class`/`size_kb` to `disposition.FIELDS` and the condition builder,
and confirmed both have "a live writer" (the scanner already computes them). What #610 did not
wire up: `handlers._evaluate_discover_lifecycle_rules`'s `doc` dict — built fresh from
`scan_inventory` for every Discover run — never included either key. A file-type or larger-than
rule validated, saved, and even previewed correctly (disposition.matches() works fine when given
a dict that already has the keys, per test_disposition_file_type_size.py's unit tests) — but at
real Discover time, `doc.get("doc_class")`/`doc.get("size_kb")` read a key that was never set, so
the condition compared against None and the rule silently matched nothing, forever. `age_days`/
`modified_age_days`-based rules were unaffected: `disposition.matches()` derives those two
internally from `created_at`/`source_modified`, which the doc dict already carried.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

OWNER = "jeremyyu.movate@gmail.com"
_PDF = "application/pdf"


@pytest.fixture()
def discover(monkeypatch, isolated_store):
    """Runs a real handlers._scan_discover over one mocked file, returning (store, run_it)."""
    import core
    import scanner
    st = isolated_store
    monkeypatch.setattr(core, "store", st)
    monkeypatch.setenv("ACP_DEFER_ANALYSIS_TO_ASSESS", "1")

    def run_it(item, scan_id="s1"):
        monkeypatch.setattr(scanner, "_list", lambda *a, **k: [item])
        import handlers
        handlers._scan_discover({"scan_id": scan_id, "source": "local", "user": OWNER},
                                {"scan_id": scan_id})
    return st, run_it


def _file(**overrides):
    base = {"name": "report.pdf", "id": "d1", "mime": _PDF, "source_mime": _PDF,
            "path": "/Finance/report.pdf", "parent_folder": "/Finance", "owner": "cfo@x.com",
            "created_at": "2018-01-01T00:00:00+00:00", "source_modified": "2019-01-01T00:00:00+00:00",
            "size_kb": 15000, "checksum": "c1"}
    base.update(overrides)
    return base


def test_a_file_type_rule_tags_a_matching_discover_time_file(discover):
    st, run_it = discover
    st.create_disposition_policy("p1", name="archive pdfs",
                                 match=json.dumps([{"field": "doc_class", "op": "eq", "value": "pdf-document"}]),
                                 action="archive", action_config="{}", requires_approval=False,
                                 enabled=True, owner_email=OWNER)
    run_it(_file())
    status = st.get_lifecycle_status("s1", "report.pdf")
    assert (status or {}).get("lifecycle_status") == "Archive Candidate"


def test_a_file_type_rule_leaves_a_non_matching_type_alone(discover):
    st, run_it = discover
    st.create_disposition_policy("p1", name="archive pdfs",
                                 match=json.dumps([{"field": "doc_class", "op": "eq", "value": "pdf-document"}]),
                                 action="archive", action_config="{}", requires_approval=False,
                                 enabled=True, owner_email=OWNER)
    _DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    run_it(_file(name="report.docx", mime=_DOCX, source_mime=_DOCX))
    status = st.get_lifecycle_status("s1", "report.docx")
    assert (status or {}).get("lifecycle_status", "Active") == "Active"


def test_a_larger_than_rule_tags_a_matching_discover_time_file(discover):
    st, run_it = discover
    st.create_disposition_policy("p1", name="archive large files",
                                 match=json.dumps([{"field": "size_kb", "op": "gt", "value": 10000}]),
                                 action="archive", action_config="{}", requires_approval=False,
                                 enabled=True, owner_email=OWNER)
    run_it(_file(size_kb=15000))
    status = st.get_lifecycle_status("s1", "report.pdf")
    assert (status or {}).get("lifecycle_status") == "Archive Candidate"


def test_a_larger_than_rule_leaves_a_smaller_file_alone(discover):
    st, run_it = discover
    st.create_disposition_policy("p1", name="archive large files",
                                 match=json.dumps([{"field": "size_kb", "op": "gt", "value": 10000}]),
                                 action="archive", action_config="{}", requires_approval=False,
                                 enabled=True, owner_email=OWNER)
    run_it(_file(size_kb=200))
    status = st.get_lifecycle_status("s1", "report.pdf")
    assert (status or {}).get("lifecycle_status", "Active") == "Active"


def test_the_inventory_row_itself_carries_doc_class_and_size_kb(discover):
    """Confirms the fix at the data layer, independent of matching: the persisted scan_inventory
    row (what the preview/conflicts fix in test_disposition_discover_only_preview.py also reads)
    has doc_class/size_kb populated from a plain Discover run, not just from a matching rule."""
    st, run_it = discover
    run_it(_file())
    row = next(r for r in st.list_inventory("s1") if r["file"] == "report.pdf")
    assert row["doc_class"] == "pdf-document"
    assert row["size_kb"] == 15000
