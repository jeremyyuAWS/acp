"""SharePoint discovery parity (audit gap G12).

Drive discovery builds a three-denominator estate summary (scope.inventory via
estate_inventory.summarize) and an honest truncation flag; SharePoint built neither — its coverage
dashboard was empty and its `truncated` fired whenever the analysis set merely equalled the cap.
These pin that _sp_list now populates scope.inventory for the WHOLE estate and truncates honestly.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

import scanner  # noqa: E402

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _item(fid, name, mime, path="/drive/root:"):
    return {"id": fid, "name": name, "file": {"mimeType": mime}, "parentReference": {"path": path}}


def test_sharepoint_builds_the_three_denominator_estate_summary(monkeypatch):
    page = {"value": [
        _item("1", "brief.docx", DOCX),
        _item("2", "photo.png", "image/png"),
        {"id": "3", "name": "Folder"},          # no "file" key → not a file item, excluded
        _item("4", "notes.txt", "text/plain"),
    ]}                                          # no nextLink → the whole estate is on one page
    monkeypatch.setattr(scanner, "_sp_get", lambda token, url: page)
    scope: dict = {}
    result = scanner._sp_list("tok", max_files=10, site=None, scope_out=scope)

    assert [r["name"] for r in result] == ["brief.docx"]      # analysis set unchanged (scannable only)
    inv = scope["inventory"]
    assert inv["discovered"] == 3                             # the WHOLE estate, not just the 1 scannable
    assert inv["by_status"]["assessable"] == 1               # docx
    assert inv["by_status"]["metadata_only"] == 1            # png
    assert inv["by_status"]["unsupported"] == 1              # txt
    assert inv["truncated"] is False                         # one page, nothing left unlisted


def test_sharepoint_truncation_is_honest_when_a_page_remains(monkeypatch):
    # cap the analysis set at 1 while a nextLink still points at unlisted files → the estate is a floor
    page = {"value": [_item("1", "a.docx", DOCX), _item("2", "b.docx", DOCX)],
            "@odata.nextLink": "https://graph.example/next"}
    monkeypatch.setattr(scanner, "_sp_get", lambda token, url: page)
    scope: dict = {}
    scanner._sp_list("tok", max_files=1, site=None, scope_out=scope)
    assert scope["inventory"]["truncated"] is True


def test_a_fully_listed_page_is_not_truncation_even_past_the_cap(monkeypatch):
    # 2 scannable on ONE page, NO nextLink: the estate was fully listed even though the analysis set
    # exceeds the cap → NOT truncated. This is the exact case the old len(result) >= cap flag got wrong.
    page = {"value": [_item("1", "a.docx", DOCX), _item("2", "b.docx", DOCX)]}
    monkeypatch.setattr(scanner, "_sp_get", lambda token, url: page)
    scope: dict = {}
    scanner._sp_list("tok", max_files=1, site=None, scope_out=scope)
    assert scope["inventory"]["discovered"] == 2
    assert scope["inventory"]["truncated"] is False
