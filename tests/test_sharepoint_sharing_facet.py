"""SharePoint sharing exposure reaches the estate drill-down (audit G10, PHI-relevant).

The estate drill-down has a "Shared first" sort and a shared badge, and _sp_list already maps a
Graph item's `shared` facet into each estate sample (owner/size/shared/modified) the same way the
Drive path does. But the facet is a $select field: without it in _SP_ITEM_SELECT, Graph never
returns it, so every `item.get("shared")` is None and the shared lens is permanently dark for a
SharePoint estate — a "shared with anyone" PHI document reads as private. These pin that the select
asks for the facet and that a shared item surfaces as shared in the estate summary.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

import scanner  # noqa: E402

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _item(fid, name, shared=None):
    return {"id": fid, "name": name, "file": {"mimeType": DOCX},
            "parentReference": {"path": "/drive/root:"}, "size": 1000,
            "lastModifiedDateTime": "2026-08-01T00:00:00Z", "shared": shared}


def test_the_select_requests_the_sharing_facet():
    # The load-bearing assertion: this is the field whose absence made the lens dark. A plumbing
    # test alone would pass on a fake _sp_get even with the facet un-requested, so pin the select.
    assert "shared" in scanner._SP_ITEM_SELECT.split(",")


def test_a_shared_item_surfaces_as_shared_in_the_estate_summary(monkeypatch):
    monkeypatch.setattr(scanner, "_sp_get", lambda token, url: {"value": [
        _item("1", "public.docx", {"scope": "anonymous"}),   # shared via an anonymous link
        _item("2", "private.docx", None),                    # not shared
    ]})
    scope: dict = {}
    scanner._sp_list("tok", max_files=10, site=None, scope_out=scope)
    by_name = {s["name"]: s for s in scope["inventory"]["samples"]["assessable"]}
    assert by_name["public.docx"]["shared"] is True
    assert by_name["private.docx"]["shared"] is False       # a missing facet is private, never a wrong True
