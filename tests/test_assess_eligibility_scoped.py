"""Scope-aware eligibility — `GET /assess/eligibility/scoped` (Phase C4c).

The plain `/assess/eligibility` counts a file eligible if any selected code has a lane for
its format. The scoped variant first RESOLVES each file's effective code-set from the
enabled scope rules (folder / owner / department / SharePoint Content Type), so a folder narrowed to a pptx-only
criterion drops the docx/xlsx/pdf files in it. Under test:

  * a folder rule that narrows a subset of files changes the eligible count and by-format,
    while files outside the folder keep the Core-17 default;
  * with no scope rules the scoped count matches the unscoped estate;
  * an empty estate (no discovery run) is zeros, never a 500.

The existing `/assess/eligibility` shape is untouched — that lives in test_assess_eligibility.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

import estate_inventory


@pytest.fixture()
def client(monkeypatch, isolated_store):
    """A TestClient with the access gate OFF (owner resolves to 'demo')."""
    import core
    from fastapi.testclient import TestClient
    from app import app

    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setattr(core, "ACCESS_CODE", "", raising=False)
    monkeypatch.setattr(core, "GOOGLE_CLIENT_ID", "", raising=False)
    monkeypatch.setattr(core, "E2E_KEY", None, raising=False)
    monkeypatch.setattr(core, "OWNER_EMAIL", "", raising=False)
    return TestClient(app), isolated_store


# One document of each supported format under Finance/, plus one docx outside it.
_INVENTORY = [
    {"file": "Finance/report.docx", "mime": "", "path": "Finance/report.docx",
     "parent_folder": "Finance", "owner": "cfo@x.com", "content_type": "Report"},
    {"file": "Finance/budget.xlsx", "mime": "", "path": "Finance/budget.xlsx",
     "parent_folder": "Finance", "owner": "cfo@x.com", "content_type": "Budget"},
    {"file": "Finance/deck.pptx", "mime": "", "path": "Finance/deck.pptx",
     "parent_folder": "Finance", "owner": "cfo@x.com", "content_type": "Presentation"},
    {"file": "Finance/manual.pdf", "mime": "", "path": "Finance/manual.pdf",
     "parent_folder": "Finance", "owner": "cfo@x.com", "content_type": "Policy"},
    {"file": "HR/handbook.docx", "mime": "", "path": "HR/handbook.docx",
     "parent_folder": "HR", "owner": "hr@x.com", "content_type": "Policy"},
    {"file": "HR/logo.png", "mime": "image/png", "path": "HR/logo.png",
     "parent_folder": "HR", "owner": "hr@x.com"},          # metadata-only, never eligible
]


def _seed(store, owner: str = "demo", sid: str = "scan01") -> None:
    """A completed discovery scan (scan_runs row) plus its per-file inventory rows, exactly
    the two writes a real discover performs (save_scan + add_inventory)."""
    store.save_scan({
        "_scan_id": sid,
        "started_at": "2026-08-18T10:00:00+00:00",
        "completed_at": "2026-08-18T10:05:00+00:00",
        "source": "drive",
        "owner": owner,
        "rubric": {"name": "wcag-aa", "hash": "h"},
        # The summarize() snapshot the unscoped /assess/eligibility reads, built from the same
        # six files so both endpoints see one estate.
        "scope": {"kind": "drive", "inventory": estate_inventory.summarize(
            [{"id": r["file"], "name": r["file"], "mimeType": r["mime"]} for r in _INVENTORY])},
        "summary": {"files": 0, "certifiable": 0, "uncertain": 0, "error": 0, "avg_score": 0},
        "files": [],
    })
    store.add_inventory(sid, _INVENTORY)


def test_scoped_no_rules_matches_the_unscoped_estate(client):
    c, store = client
    _seed(store)
    body = c.get("/assess/eligibility/scoped").json()
    assert body["discovered"] == 6
    # No rules → every file keeps the Core-17 default: docx/xlsx/pptx/pdf eligible, png not.
    assert body["eligible"] == 5
    assert body["by_format"] == {"docx": 2, "pdf": 1, "pptx": 1, "xlsx": 1}
    assert body["rules_applied"] == 0


def test_folder_rule_narrows_the_subset_it_targets(client):
    c, store = client
    _seed(store)
    # An OVERRIDE on Finance/ scoping it to 2.1.1 (Keyboard) — a pptx-only lane. Only the
    # Finance .pptx stays eligible there; the Finance docx/xlsx/pdf drop. HR/ is untouched,
    # so its .docx keeps the Core-17 default (the .png is still metadata-only).
    store.create_scope_rule(
        "r-fin", name="Finance keyboard-only", selector="folder", value="Finance",
        codes=["2.1.1"], priority=10, is_override=True, enabled=True, created_by="demo")

    body = c.get("/assess/eligibility/scoped").json()
    assert body["discovered"] == 6
    assert body["by_format"] == {"docx": 1, "pptx": 1}   # HR docx + Finance pptx
    assert body["eligible"] == 2
    assert body["rules_applied"] == 1


def test_disabled_rule_does_not_apply(client):
    c, store = client
    _seed(store)
    store.create_scope_rule(
        "r-off", name="disabled", selector="folder", value="Finance",
        codes=["2.1.1"], priority=10, is_override=True, enabled=False, created_by="demo")
    body = c.get("/assess/eligibility/scoped").json()
    # enabled_only=True means the disabled rule is invisible → full Core-17 estate.
    assert body["eligible"] == 5
    assert body["rules_applied"] == 0


def test_sharepoint_content_type_rule_reaches_inventory(client):
    c, store = client
    _seed(store)
    store.create_scope_rule(
        "r-policy", name="Policy keyboard-only", selector="content_type", value="policy",
        codes=["2.1.1"], priority=10, is_override=True, enabled=True, created_by="demo")

    body = c.get("/assess/eligibility/scoped").json()
    # Both Policy documents are docx/pdf and 2.1.1 has only a PowerPoint lane, so they drop.
    assert body["eligible"] == 3
    assert body["by_format"] == {"pptx": 1, "xlsx": 1, "docx": 1}
    assert body["rules_applied"] == 1


def test_codes_query_sets_the_default_for_unmatched_files(client):
    c, store = client
    _seed(store)
    # Default narrowed to 2.1.1 (pptx-only) and no rules → only the two .pptx-lane files...
    body = c.get("/assess/eligibility/scoped", params={"codes": "2.1.1"}).json()
    assert body["by_format"] == {"pptx": 1}
    assert body["eligible"] == 1


def test_empty_estate_is_zeros_not_error(client):
    c, _ = client
    res = c.get("/assess/eligibility/scoped")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body == {"discovered": 0, "eligible": 0, "by_format": {}, "rules_applied": 0}


def test_existing_unscoped_endpoint_still_works(client):
    """C4c must not disturb the C2 shape: /assess/eligibility is unchanged."""
    c, store = client
    _seed(store)
    body = c.get("/assess/eligibility").json()
    assert body["discovered"] == 6
    assert "rules_applied" not in body        # the plain endpoint never grew the field
