"""Whole-Drive discovery uses Google's complete user corpus and never hides incomplete results."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

import scanner  # noqa: E402


class _Exec:
    def __init__(self, payload):
        self.payload = payload

    def execute(self, **_kwargs):
        return self.payload


class _Files:
    def __init__(self, payload):
        self.payload = payload
        self.kwargs = None

    def list(self, **kwargs):
        self.kwargs = kwargs
        return _Exec(self.payload)


class _Svc:
    def __init__(self, payload):
        self.api = _Files(payload)

    def files(self):
        return self.api


def test_whole_drive_uses_the_user_corpus_owned_by_or_shared_to_the_user():
    svc = _Svc({"files": [{"id": "f1", "name": "Policy.pdf"}]})

    rows, incomplete = scanner._list_drive_page_all(svc, "trashed=false", 500)

    assert [row["id"] for row in rows] == ["f1"]
    assert incomplete is False
    assert svc.api.kwargs["corpora"] == "user"
    assert svc.api.kwargs["spaces"] == "drive"
    assert svc.api.kwargs["includeItemsFromAllDrives"] is True
    assert "incompleteSearch" in svc.api.kwargs["fields"]


def test_google_incomplete_search_marks_the_inventory_as_incomplete():
    svc = _Svc({"files": [{"id": "f1", "name": "Policy.pdf"}], "incompleteSearch": True})

    _rows, incomplete = scanner._list_drive_page_all(svc, "trashed=false", 500)

    assert incomplete is True
