"""Live SharePoint folder traversal reaches Discovery without adding Graph requests."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

import scanner  # noqa: E402


def _folder(fid, name):
    return {"id": fid, "name": name, "folder": {"childCount": 1}}


def _file(fid, name):
    return {"id": fid, "name": name, "file": {}}


def test_walk_reports_exact_nested_folder_paths_without_extra_requests(monkeypatch):
    calls = []

    def get(_token, url):
        calls.append(url)
        if "/root/children" in url:
            return {"value": [_folder("clinical", "Clinical"), _file("root-doc", "root.docx")]}
        if "/items/clinical/children" in url:
            return {"value": [_folder("policies", "Policies"), _file("clinical-doc", "c.docx")]}
        if "/items/policies/children" in url:
            return {"value": [_file("policy-doc", "p.docx")]}
        raise AssertionError(url)

    monkeypatch.setattr(scanner, "_sp_get", get)
    events = []
    rows, truncated = scanner._sp_walk_folder(
        "tok", "drive-1", "root", 20, {".docx"}, progress_cb=events.append,
        root_label="Documents")

    assert truncated is False
    assert [row["name"] for row in rows] == ["root.docx", "c.docx", "p.docx"]
    assert len(calls) == 3, "telemetry must reuse listing responses, never add a Graph lookup"
    assert [event["path"] for event in events if event["state"] == "scanning"] == [
        "Documents", "Documents/Clinical", "Documents/Clinical/Policies"]
    assert [(event["path"], event["files_found"]) for event in events
            if event["state"] == "completed"] == [
        ("Documents", 1), ("Documents/Clinical", 1), ("Documents/Clinical/Policies", 1)]


def test_walk_reports_the_folder_that_failed_before_preserving_the_error(monkeypatch):
    monkeypatch.setattr(scanner, "_sp_get", lambda _token, _url:
                        (_ for _ in ()).throw(PermissionError("Graph 403")))
    events = []
    try:
        scanner._sp_walk_folder("tok", "drive-1", "root", 20, {".docx"},
                                progress_cb=events.append, root_label="Records")
    except PermissionError:
        pass
    else:
        raise AssertionError("the listing failure was swallowed")

    assert events[-1]["state"] == "failed"
    assert events[-1]["path"] == "Records"
    assert events[-1]["error"] == "Graph 403"


def test_multisite_listing_forwards_bounded_folder_activity(monkeypatch):
    monkeypatch.setattr(scanner, "_sp_drives", lambda _token, _site:
                        [{"id": "d1", "name": "Documents"}])
    monkeypatch.setattr(scanner, "_sp_site_name", lambda _token, _site: "Clinical")
    monkeypatch.setattr(scanner, "_sp_get", lambda _token, _url:
                        {"value": [_folder("policies", "Policies"), _file("one", "one.docx")]}
                        if "/root/children" in _url else
                        {"value": [_file("two", "two.docx")]})
    ticks = []

    scanner._sp_list("tok", 20, sites=["s1"], progress_cb=lambda count, **detail:
                     ticks.append((count, detail)))

    assert any(t[1].get("active") for t in ticks)
    final = ticks[-1][1]
    assert final["folders"] == 2
    assert final["recent"][0]["path"] == "Documents/Policies"
    assert final["recent"][0]["library_name"] == "Documents"
