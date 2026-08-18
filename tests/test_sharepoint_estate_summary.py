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


def test_estate_samples_carry_triage_metadata_like_drive(monkeypatch):
    # The drill-down's owner / biggest-first / shared lenses read _sample_meta(owners[]/size/shared/
    # modifiedTime). The SharePoint estate row must map the Graph item's own field names into those,
    # or every SharePoint sample comes back with a blank owner, no size and not-shared (the gap).
    item = {"id": "1", "name": "brief.docx", "file": {"mimeType": DOCX},
            "parentReference": {"path": "/drive/root:"},
            "size": 2048, "shared": {"scope": "users"},
            "createdBy": {"user": {"displayName": "Dana Owner", "email": "dana@x.com"}},
            "lastModifiedDateTime": "2024-06-01T00:00:00Z"}
    monkeypatch.setattr(scanner, "_sp_get", lambda token, url: {"value": [item]})
    scope: dict = {}
    scanner._sp_list("tok", max_files=10, site=None, scope_out=scope)
    sample = scope["inventory"]["samples"]["assessable"][0]
    assert sample["owner"] == "Dana Owner"
    assert sample["size"] == 2048
    assert sample["shared"] is True
    assert sample["modified"] == "2024-06-01T00:00:00Z"


# ── multi-library (SharePoint site) truncation — the branch OneDrive tests can't reach ──
def test_multi_library_truncation_when_a_later_library_is_never_reached(monkeypatch):
    # A SITE with two document libraries. The scannable cap (1) is filled in the FIRST library, so
    # the for-loop over targets breaks and the SECOND library is never listed → the estate is a
    # floor and must be truncated (the `i < len(targets) - 1` arm, unreachable from OneDrive tests).
    monkeypatch.setattr(scanner, "_sp_drives",
                        lambda token, site: [{"id": "libA"}, {"id": "libB"}])

    def sp_get(token, url):
        assert "libB" not in url, "libB must never be fetched — the cap was hit in libA"
        return {"value": [_item("1", "a.docx", DOCX), _item("2", "b.docx", DOCX)]}
    monkeypatch.setattr(scanner, "_sp_get", sp_get)

    scope: dict = {}
    scanner._sp_list("tok", max_files=1, site="contoso.sharepoint.com,g1,g2", scope_out=scope)
    assert scope["inventory"]["truncated"] is True
    assert scope["inventory"]["discovered"] == 2          # a floor: only libA was listed


def test_multi_library_is_not_truncation_when_every_library_is_fully_listed(monkeypatch):
    # Two libraries, both fully listed under the cap → NOT truncated, and the estate spans both
    # (the False side of the same branch: a fully-read multi-library site is complete, not a floor).
    monkeypatch.setattr(scanner, "_sp_drives",
                        lambda token, site: [{"id": "libA"}, {"id": "libB"}])

    def sp_get(token, url):
        return {"value": [_item("1", "a.docx", DOCX)]} if "libA" in url \
            else {"value": [_item("2", "b.docx", DOCX)]}
    monkeypatch.setattr(scanner, "_sp_get", sp_get)

    scope: dict = {}
    result = scanner._sp_list("tok", max_files=10, site="contoso.sharepoint.com,g1,g2", scope_out=scope)
    assert sorted(r["name"] for r in result) == ["a.docx", "b.docx"]   # both libraries scanned
    assert scope["inventory"]["discovered"] == 2
    assert scope["inventory"]["truncated"] is False
